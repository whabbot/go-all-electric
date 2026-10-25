"""One analysis call: EPC record, verified photo and bill readings, weather, then the maths core.

Order of work:
1. The EPC fetch and every photo/bill extraction start together (each extraction is its own
   Gemini verification loop, so they are independent).
2. The bill reading plus the postcode centroid's exact-period degree days give Estimate B.
3. The maths core runs: fabric (A), measured (B), cross-check, costs and target spec.
4. The survey is saved to Atlas with the postcode district only.

Every log entry is emitted as it happens, so the UI shows the real verification loop live.
Photos and bills stay in memory for this call: they are never stored, logged or returned.
"""

import calendar
import logging
import math
import time
from collections.abc import Callable, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import date
from threading import Lock
from typing import Any

from pydantic import PrivateAttr

from gae.db.datasheets import DatasheetLookup
from gae.db.models import Reading as StoredReading
from gae.db.models import SurveyInput
from gae.gemini.client import GeminiError, StructuredModel
from gae.gemini.extract import SPECS, extract
from gae.gemini.schemas import (
    BoilerPlateReading,
    GasBillReading,
    PhotoKind,
    RadiatorReading,
    RadiatorVideoResult,
    Reading,
    VerificationLog,
    VerificationLogEntry,
    VerifiedReading,
)
from gae.gemini.video import apply_radiator_spec_checks, extract_radiator_video
from gae.heatpump import constants as c
from gae.heatpump.constants import HeatingFuel
from gae.heatpump.costs import compare_running_costs
from gae.heatpump.crosscheck import cross_check
from gae.heatpump.fabric import estimate_fabric
from gae.heatpump.measured import MeasuredCaveat, MeasuredEstimate
from gae.heatpump.spec import Room, target_spec
from gae.opendata.bill import DegreeDayProvider
from gae.opendata.mapping import FabricMapping, FieldConfidence, descriptions
from gae.opendata.usage import UsagePeriod, measured_from_periods, select_periods
from gae.opendata.weather import normalise_postcode
from gae.plan.build import build_all_electric_plan
from gae.plan.solar import SolarYieldProvider
from gae.survey.fields import NamedDefault
from gae.survey.known import Disagreement, KnownDetails, apply_entered, entered_for
from gae.survey.schemas import (
    AnalysisBundle,
    AnalysisResult,
    EpcSummary,
    Gap,
    InputReading,
    jsonable,
)

COST_FLOW_TEMPS_C = (40, 45, 50, 55)
USED_FOR = {
    PhotoKind.BOILER_PLATE: "heating fuel for the grant; boiler model checked against datasheets",
    PhotoKind.RADIATORS: "radiator check at the target flow temperature",
    PhotoKind.FUSE_CUTOUT: "electricity supply headroom for the all-electric plan",
    PhotoKind.OUTDOOR_SPACE: "whether an outdoor unit fits",
    PhotoKind.GAS_BILL: "Estimate B, measured from what the house actually used",
    PhotoKind.LOFT: (
        "evidence for the review to test whether EPC loft insulation depth is out of date"
    ),
}

Emit = Callable[[dict[str, Any]], None]


class AnalysisRefused(Exception):
    """The analysis can't be done honestly for this input (for example a flat)."""

    def __init__(self, message: str, status_code: int = 422):
        super().__init__(message)
        self.status_code = status_code


@dataclass
class Services:
    """Everything the analysis talks to, so tests can swap in fakes."""

    gemini: StructuredModel
    epc: Callable[[str], tuple[dict, FabricMapping]]
    weather: DegreeDayProvider
    datasheets: DatasheetLookup
    save: Callable[[SurveyInput], str]
    solar: SolarYieldProvider


class LiveLog(VerificationLog):
    """A verification log that emits each entry as it is added, with ids unique per call."""

    _prefix: str = PrivateAttr()
    _on_add: Callable[[VerificationLogEntry], None] = PrivateAttr()

    def __init__(self, prefix: str, on_add: Callable[[VerificationLogEntry], None]):
        super().__init__()
        self._prefix = prefix
        self._on_add = on_add

    def add(self, *args: Any, **kwargs: Any) -> None:
        super().add(*args, **kwargs)
        entry = self.entries[-1]
        entry.id = f"{self._prefix}-{entry.id}"
        self._on_add(entry)


def run_analysis(
    services: Services,
    certificate_id: str,
    files: dict[PhotoKind, tuple[bytes, str]],
    emit: Emit = lambda event: None,
    radiator_video: tuple[bytes, str] | None = None,
    radiator_files: Sequence[Sequence[tuple[bytes, str]]] | None = None,
    known: KnownDetails | None = None,
    bill_files: Sequence[tuple[bytes, str]] | None = None,
) -> AnalysisResult:
    """`radiator_files` holds each radiator's photos (radiator 1 first): one radiator may have
    several photos, read together as one radiator. `known` holds what the homeowner entered."""
    started = time.monotonic()
    timings: dict[str, int] = {}
    entries: list[VerificationLogEntry] = []
    lock = Lock()

    rad_groups: list[list[tuple[bytes, str]]] = (
        [list(group) for group in radiator_files]
        if radiator_files is not None
        else ([[files[PhotoKind.RADIATORS]]] if PhotoKind.RADIATORS in files else [])
    )
    known_rads = known.radiators if known is not None else []
    rad_count = max(len(rad_groups), len(known_rads))
    rad_groups += [[] for _ in range(rad_count - len(rad_groups))]
    rad_entered = [
        known_rads[idx].values() if idx < len(known_rads) else {} for idx in range(rad_count)
    ]
    bill_uploads = (
        list(bill_files)
        if bill_files is not None
        else ([files[PhotoKind.GAS_BILL]] if PhotoKind.GAS_BILL in files else [])
    )
    other_files = {
        k: v for k, v in files.items() if k not in (PhotoKind.RADIATORS, PhotoKind.GAS_BILL)
    }

    def record(entry: VerificationLogEntry) -> None:
        with lock:
            entries.append(entry)
        emit({"type": "log", "entry": entry.model_dump(mode="json")})

    def step(name: str, status: str) -> None:
        emit({"type": "step", "step": name, "status": status, "ms": timings.get(name)})

    code_log = LiveLog("survey", record)

    def timed[T](name: str, fn: Callable[..., T], *args: Any) -> T:
        step(name, "running")
        t0 = time.monotonic()
        try:
            return fn(*args)
        finally:
            timings[name] = round((time.monotonic() - t0) * 1000)
            step(name, "done")

    def read(
        kind: PhotoKind,
        data: bytes,
        mime: str,
        prefix: str | None = None,
        more: list[tuple[bytes, str]] | None = None,
    ) -> VerifiedReading | None:
        log_prefix = prefix or kind.value
        try:
            return extract(
                services.gemini,
                services.datasheets,
                kind,
                data,
                mime,
                media_parts=more,
                log=LiveLog(log_prefix, record),
                purpose=f"/api/analysis:{kind.value}",
            )
        except GeminiError as exc:
            detail = (
                "Gemini quota/billing limit reached"
                if exc.upstream_status == 429
                else "Gemini call failed"
            )
            code_log.add("fail", kind, "code", detail, False, "couldn't tell: try again")
            return None

    def read_video(data: bytes, mime: str) -> RadiatorVideoResult | None:
        try:
            return extract_radiator_video(
                services.gemini,
                data,
                mime,
                log=LiveLog("radiator_video", record),
                purpose="/api/analysis:radiators_video",
            )
        except GeminiError as exc:
            detail = (
                "Gemini quota/billing limit reached"
                if exc.upstream_status == 429
                else "Gemini call failed"
            )
            code_log.add(
                "fail",
                "radiator_video",
                "code",
                detail,
                False,
                "couldn't tell: try again",
            )
            return None

    rad_photos = [group for group in rad_groups if group]
    workers = (
        1
        + len(bill_uploads)
        + len(other_files)
        + len(rad_photos)
        + (1 if radiator_video is not None else 0)
    )
    with ThreadPoolExecutor(max_workers=workers) as pool:
        epc_future = pool.submit(timed, "epc", services.epc, certificate_id)
        futures: dict[PhotoKind, Future] = {
            kind: pool.submit(timed, f"read_{kind.value}", read, kind, data, mime)
            for kind, (data, mime) in other_files.items()
        }
        bill_t0 = time.monotonic()
        if bill_uploads:
            step("read_gas_bill", "running")
        bill_futures = [
            pool.submit(read, PhotoKind.GAS_BILL, data, mime, f"gas_bill-{i + 1}")
            for i, (data, mime) in enumerate(bill_uploads)
        ]
        rad_t0 = time.monotonic()
        if rad_photos:
            step("read_radiators", "running")
        # One Gemini read per radiator, with all of that radiator's photos; none without photos.
        rad_futures: list[Future[VerifiedReading | None] | None] = [
            pool.submit(
                read,
                PhotoKind.RADIATORS,
                group[0][0],
                group[0][1],
                "radiators" if idx == 0 else f"radiators-{idx + 1}",
                group[1:],
            )
            if group
            else None
            for idx, group in enumerate(rad_groups)
        ]
        video_future: Future[RadiatorVideoResult | None] | None = (
            pool.submit(
                timed,
                "read_radiator_video",
                read_video,
                radiator_video[0],
                radiator_video[1],
            )
            if radiator_video is not None
            else None
        )
        try:
            raw, mapping = epc_future.result()
        except Exception:
            pool.shutdown(wait=False, cancel_futures=True)
            raise
        verified = {kind: future.result() for kind, future in futures.items()}
        bill_verified = [f.result() for f in bill_futures]
        if bill_uploads:
            timings["read_gas_bill"] = round((time.monotonic() - bill_t0) * 1000)
            step("read_gas_bill", "done")
        if rad_photos:
            try:
                rad_verified = [f.result() if f is not None else None for f in rad_futures]
            finally:
                timings["read_radiators"] = round((time.monotonic() - rad_t0) * 1000)
                step("read_radiators", "done")
        else:
            rad_verified = [None] * rad_count
        video_result = video_future.result() if video_future is not None else None

    if known and (known.house_type is not None or known.floor_area_m2 is not None):
        inputs, confidence = dict(mapping.fabric_inputs), dict(mapping.confidence)
        # An explicit flat/maisonette/park-home signal cannot be turned into a house.
        non_house = not mapping.house_model_supported
        if known.house_type is not None and not non_house:
            inputs["property_type"] = known.house_type
            inputs["storeys"] = 1 if known.house_type.value == "bungalow" else 2
            confidence["property_type"] = FieldConfidence(
                "medium", "Entered by you", "House type (you); confirm at survey."
            )
        if known.floor_area_m2 is not None:
            inputs["floor_area_m2"] = known.floor_area_m2
            confidence["floor_area_m2"] = FieldConfidence(
                "medium", "Entered by you", "Floor area (you); confirm at survey."
            )
        estimate = None
        reason = mapping.reason
        if not non_house and inputs["floor_area_m2"] is not None:
            try:
                estimate = estimate_fabric(**inputs)
                reason = None
            except ValueError:
                reason = (
                    "Couldn't tell: EPC geometry is inconsistent. Confirm dimensions at survey."
                )
        logging.getLogger(__name__).warning(
            "epc_geometry property_type=%r built_form=%r dwelling_type=%r path=%s",
            raw.get("property_type"),
            raw.get("built_form"),
            raw.get("dwelling_type"),
            "explicit_non_house" if non_house else "homeowner",
        )
        mapping = replace(
            mapping, fabric_inputs=inputs, confidence=confidence, estimate=estimate, reason=reason
        )
        code_log.add(
            "check",
            "epc",
            "code",
            "House details entered by you",
            True,
            "Use entered details; confirm at survey",
        )
    if mapping.estimate is None:
        code_log.add(
            "fail",
            "epc",
            "code",
            "EPC maps to the house heat-loss model",
            False,
            "continue without fabric estimate",
        )
    fabric = mapping.estimate
    defaults = _epc_defaults(mapping)
    if fabric is not None:
        code_log.add(
            "check",
            "epc",
            "code",
            "EPC record maps to fabric inputs",
            True,
            f"Estimate A uses {len(defaults)} named default(s)",
        )

    district = None
    postcode = None
    try:
        postcode = normalise_postcode(str(raw.get("postcode", "")))
        district = postcode.split()[0]
    except ValueError:
        pass

    usage = known.gas_bill.usage() if known and known.gas_bill else []
    shape: list[UsagePeriod] = []
    bill_disagreements: list[Disagreement] = []
    for i, result in enumerate(bill_verified):
        photo_bill = _reading(result, GasBillReading)
        if (
            photo_bill
            and photo_bill.period_start
            and photo_bill.period_end
            and photo_bill.total_kwh
        ):
            usage.append(
                UsagePeriod(
                    photo_bill.period_start,
                    photo_bill.period_end,
                    photo_bill.total_kwh,
                    f"Bill photo {i + 1}",
                )
            )
            for row in photo_bill.monthly:
                try:
                    start = date.fromisoformat(row.month + "-01")
                    end = date(
                        start.year, start.month, calendar.monthrange(start.year, start.month)[1]
                    )
                    if (
                        photo_bill.period_start <= start <= end <= photo_bill.period_end
                        and row.kwh > 0
                    ):
                        shape.append(
                            UsagePeriod(start, end, row.kwh, f"Bill photo {i + 1} monthly usage")
                        )
                except ValueError:
                    pass
    chosen, bill_notes = select_periods(usage)
    for entry in [p for p in usage if p.entered]:
        for photo in [
            p for p in usage if not p.entered and p.start == entry.start and p.end == entry.end
        ]:
            if abs(photo.kwh - entry.kwh) > 0.05 * entry.kwh:
                bill_disagreements.append(
                    Disagreement(field="total_kwh", entered=entry.kwh, read=photo.kwh)
                )
    for container in chosen:
        children, _ = select_periods(
            [
                p
                for p in usage
                if container.start <= p.start
                and p.end <= container.end
                and (p.start, p.end) != (container.start, container.end)
            ]
        )
        if sum(p.kwh for p in children) > container.kwh * 1.05:
            bill_notes.append(
                f"Usage inside {container.source} totals more than its "
                f"{container.kwh:,.0f} kWh: check both figures."
            )
            bill_disagreements.append(
                Disagreement(
                    field="total_kwh", entered=container.kwh, read=sum(p.kwh for p in children)
                )
            )
    all_months, _ = select_periods(
        [
            p
            for p in [*usage, *shape]
            if p.start.day == 1
            and p.end
            == date(
                p.start.year, p.start.month, calendar.monthrange(p.start.year, p.start.month)[1]
            )
        ]
    )
    combined_bill = (
        GasBillReading(
            legible=True,
            confidence="medium",
            notes="Used periods: "
            + "; ".join(
                f"{p.start.isoformat()} to {p.end.isoformat()}: {p.kwh:g} kWh" for p in chosen
            ),
            supplier=None,
            period_start=chosen[0].start,
            period_end=chosen[-1].end,
            total_kwh=sum(p.kwh for p in chosen),
            monthly=[{"month": p.start.strftime("%Y-%m"), "kwh": p.kwh} for p in all_months],
            estimated_reading=None,
        )
        if chosen
        else None
    )
    gaps: list[Gap] = []
    if fabric is None:
        gaps.append(
            Gap(
                input="epc",
                message=mapping.reason or "Couldn't compute the fabric estimate.",
                provide="On Start, add your house type and floor area under Add details you know; "
                "confirm geometry at survey. Flats, maisonettes and park homes "
                "use the bill estimate only. "
                "The A-vs-B cross-check and disagreement reasons are unavailable.",
            )
        )
    readings: list[InputReading] = []
    rad_items: list[InputReading] = []
    for kind in PhotoKind:
        if kind is PhotoKind.GAS_BILL:
            if combined_bill:
                values = combined_bill.model_dump(mode="json")
                entered_values = (
                    {k: values[k] for k in ("total_kwh", "period_start", "period_end")}
                    if any(p.entered for p in chosen)
                    else {}
                )
                readings.append(
                    InputReading(
                        kind=kind,
                        used_for=USED_FOR[kind],
                        status="entered" if entered_values else "verified",
                        attempts=len(bill_uploads),
                        reading=values,
                        entered=entered_values,
                        warnings=bill_notes,
                        disagreements=bill_disagreements,
                        photograph_instead=None,
                    )
                )
            else:
                readings.append(_summary(kind, None, bool(bill_uploads)))
            continue
        if kind is PhotoKind.RADIATORS:
            for idx in range(rad_count):
                photos, entered = rad_groups[idx], rad_entered[idx]
                if not photos and not entered:
                    continue  # an empty radiator card counts for nothing
                result = rad_verified[idx]
                item = _summary(kind, result, bool(photos), entered, index=idx)
                rad_items.append(item)
                if photos and item.status == "couldnt_tell":
                    what = "photos" if len(photos) > 1 else "photo"
                    gaps.append(
                        Gap(
                            input=kind.value,
                            message=f"Couldn't tell from the {what} of radiator {idx + 1}.",
                            provide=f"Photograph {SPECS[kind].photograph_instead}, or add "
                            "the details you know.",
                        )
                    )
            readings.extend(rad_items or [_summary(kind, None, False)])
            continue
        result = verified.get(kind)
        item = _summary(kind, result, kind in other_files, entered_for(known, kind))
        readings.append(item)
        if kind in other_files and item.status == "couldnt_tell":
            gaps.append(
                Gap(
                    input=kind.value,
                    message=f"Couldn't tell from the {_label(kind)} photo.",
                    provide=f"Photograph {SPECS[kind].photograph_instead}.",
                )
            )

    # --- Estimate B: bill + exact-period degree days -----------------------------------------
    measured: MeasuredEstimate | None = None
    annual_gas_kwh: float | None = None
    by_kind = {item.kind: item for item in readings if item.kind is not PhotoKind.RADIATORS}
    bill = combined_bill
    bill_warning = None
    costs_annualised = False
    if known and known.gas_bill:
        code_log.add(
            "pass",
            "gas_bill",
            "code",
            "Entered by you",
            True,
            "Gas kWh and inclusive dates entered by you",
        )
    if bill is None or postcode is None:
        gaps.append(
            Gap(
                input="gas_bill",
                message="Couldn't tell: add gas usage with dates, including a winter month.",
                provide="Add bill photos or enter gas kWh and dates under Add details you know.",
            )
        )
    else:
        outcome = timed(
            "weather",
            lambda: measured_from_periods(
                periods=usage,
                shape=shape,
                postcode=postcode,
                weather_client=services.weather,
                monthly=_monthly(bill),
            ),
        )
        if outcome.estimate is not None:
            measured = outcome.estimate
            annual_gas_kwh = outcome.annual_gas_kwh
            bill_warning = outcome.warning
            costs_annualised = outcome.annualised
            code_log.add(
                "check",
                "gas_bill",
                "code",
                "Exact-period weather and gas usage",
                True,
                "Estimate B from your usage",
            )
            code_log.add(
                "check",
                "gas_bill",
                "code",
                "Summer usage for the hot-water baseline",
                MeasuredCaveat.BASELINE_ESTIMATED not in measured.caveats,
                "Use summer usage"
                if MeasuredCaveat.BASELINE_ESTIMATED not in measured.caveats
                else "Use default baseline share",
            )
        else:
            gaps.append(
                Gap(
                    input="gas_bill",
                    message=outcome.reason or "Couldn't tell: add a winter month.",
                    provide="Add a winter month with gas kWh and start/end dates; "
                    "12 months in a row is best.",
                )
            )
    if measured is not None and MeasuredCaveat.EFFICIENCY_DEFAULTED in measured.caveats:
        defaults.append(
            NamedDefault(
                input="boiler_plate",
                name="boiler_efficiency",
                value=f"{c.DEFAULT_BOILER_EFFICIENCY:.0%}",
                note="Typical in-use seasonal efficiency of a condensing gas boiler; data "
                "plates do not state it. The measured range is widened.",
                confidence="low",
            )
        )

    # --- Heating fuel (grant) -----------------------------------------------------------------
    fuel = mapping.main_heating_fuel
    boiler = _typed(by_kind[PhotoKind.BOILER_PLATE], BoilerPlateReading)
    if fuel is HeatingFuel.OTHER and boiler is not None and boiler.fuel == "natural_gas":
        fuel = HeatingFuel.GAS
        code_log.add("check", "boiler_plate", "code", "fuel from data plate", True, "gas")
    elif boiler is None or boiler.fuel == "unknown":
        defaults.append(
            NamedDefault(
                input="boiler_plate",
                name="heating_fuel_from_epc",
                value=fuel.value,
                note="Heating fuel taken from the EPC main heating description.",
                confidence="medium" if fuel is not HeatingFuel.OTHER else "low",
            )
        )

    # --- Maths core ---------------------------------------------------------------------------
    t0 = time.monotonic()
    if measured is None and fabric is None:
        raise AnalysisRefused(
            "Couldn't tell: neither estimate is available. "
            "To size this home, add your house type and floor "
            "area under Add details you know on Start, or add gas usage with start/end dates "
            "including a winter month on Photos. Confirm unsupported geometry at survey."
        )
    basis = measured.design_load_kw if measured else fabric.design_load_kw
    radiator_readings = [
        (item, r) for item in rad_items if (r := _typed(item, RadiatorReading)) is not None
    ]
    rooms = _rooms(radiator_readings, basis.central, defaults)
    if radiator_readings and not rooms:
        gaps.append(
            Gap(
                input="radiators",
                message="Couldn't rate these radiators: the type, width and height are all needed.",
                provide="Add the type and size under each radiator's details, or its make and "
                "model label.",
            )
        )
    if radiator_video is not None and video_result is None:
        gaps.append(
            Gap(
                input="radiators",
                message="Couldn't tell from the radiator video right now.",
                provide=f"Photograph {SPECS[PhotoKind.RADIATORS].photograph_instead}.",
            )
        )
    elif video_result is not None:
        video_rooms = apply_radiator_spec_checks(
            video_result.radiators,
            design_load_kw=basis.central,
            flow_temp_c=c.TARGET_FLOW_TEMP_C,
        )
        rooms.extend(video_rooms)
        if video_rooms:
            share = c.PHOTOGRAPHED_ROOM_SHARE_OF_HEAT_LOSS
            loss = basis.central * 1000 * share
            defaults.append(
                NamedDefault(
                    input="radiators",
                    name="radiator_rating_from_video",
                    value=f"{len(video_rooms)} radiator(s) rated at ΔT50",
                    note="Radiator types and dimensions estimated from the walk-through video, "
                    f"each checked against {share:.0%} of {basis.central:.1f} kW ({loss:,.0f} W) "
                    f"at {c.TARGET_FLOW_TEMP_C:g}°C flow.",
                    confidence="low",
                )
            )
        for req in video_result.photo_requests:
            gaps.append(
                Gap(
                    input="radiators",
                    message=req,
                    provide=f"Photograph {SPECS[PhotoKind.RADIATORS].photograph_instead}.",
                )
            )
        if video_result.status == "couldnt_tell" and not video_result.photo_requests:
            gaps.append(
                Gap(
                    input="radiators",
                    message="Couldn't tell from the radiator walk-through video.",
                    provide=f"Photograph {SPECS[PhotoKind.RADIATORS].photograph_instead}.",
                )
            )
    check = cross_check(fabric, measured) if measured and fabric else None
    costs = (
        [
            compare_running_costs(
                annual_gas_kwh=annual_gas_kwh,
                heating_gas_kwh=measured.heating_gas_kwh.central,
                boiler_efficiency=measured.boiler_efficiency,
                design_flow_temp_c=flow,
            )
            for flow in COST_FLOW_TEMPS_C
        ]
        if measured and annual_gas_kwh
        else []
    )
    spec = target_spec(measured_design_load_kw=basis, current_fuel=fuel, rooms=rooms)
    timings["maths"] = round((time.monotonic() - t0) * 1000)
    if check is not None:
        code_log.add(
            "check",
            "maths",
            "code",
            f"Estimate A vs B: ratio {check.ratio.central:.2f} ({check.verdict.value})",
            check.verdict.value == "agree",
            "estimates agree"
            if check.verdict.value == "agree"
            else f"explain the gap: {len(check.reasons)} ranked reason(s)",
        )
    elif fabric is not None:
        code_log.add(
            "check",
            "maths",
            "code",
            "Estimate A vs B: no measured estimate to compare",
            False,
            "can't compare; size from the fabric estimate and say so",
        )
        defaults.append(
            NamedDefault(
                input="gas_bill",
                name="size_from_fabric_estimate",
                value=f"{spec.size_kw.low:g}-{spec.size_kw.high:g} kW",
                note="Without a bill the size comes from the installer-style fabric calc, "
                "which often reads high. Add a bill to size from measured use.",
                confidence="low",
            )
        )

    bundle = AnalysisBundle(
        measured=jsonable(measured) if measured else None,
        fabric=jsonable(fabric) if fabric else None,
        cross_check=jsonable(check) if check else None,
        costs_by_flow_temp=[jsonable(x) for x in costs],
        target_spec=jsonable(spec),
    )
    epc = _epc_summary(raw, mapping, fuel)
    epc.entered = [
        field for field, conf in mapping.confidence.items() if conf.source == "Entered by you"
    ]

    t0 = time.monotonic()
    step("plan", "running")
    plan = build_all_electric_plan(
        postcode_district=district,
        readings=readings,
        bundle=bundle.model_dump(mode="json"),
        solar=services.solar,
    )
    defaults.extend(plan.defaults)
    timings["plan"] = round((time.monotonic() - t0) * 1000)
    step("plan", "done")

    # --- Save (postcode district only) ---------------------------------------------------------
    survey_id = None
    note = None
    t0 = time.monotonic()
    step("save", "running")
    try:
        survey_id = services.save(
            _survey(district, epc, readings, bundle, "measured" if measured else "fabric", entries)
        )
    except Exception:
        # Driver errors can include hosts or credentials: report only that saving failed.
        note = "Not saved: the survey store is unavailable. Nothing else is affected."
    timings["save"] = round((time.monotonic() - t0) * 1000)
    step("save", "done")
    timings["total"] = round((time.monotonic() - started) * 1000)

    return AnalysisResult(
        survey_id=survey_id,
        saved=survey_id is not None,
        storage_note=note,
        postcode_district=district,
        epc=epc,
        bundle=bundle,
        size_basis="measured" if measured else "fabric",
        readings=readings,
        radiator_video=video_result,
        gaps=gaps,
        defaults=defaults,
        plan=plan,
        log=sorted(entries, key=lambda e: e.at),
        timings_ms=timings,
        bill_warning=bill_warning,
        bill_notes=bill_notes,
        costs_annualised=costs_annualised,
    )


def _label(kind: PhotoKind) -> str:
    return kind.value.replace("_", " ")


def _reading[T](result: VerifiedReading | None, schema: type[T]) -> T | None:
    if result is None or result.reading is None or not isinstance(result.reading, schema):
        return None
    return result.reading


def _summary(
    kind: PhotoKind,
    result: VerifiedReading | None,
    provided: bool,
    entered: dict[str, Any] | None = None,
    index: int | None = None,
) -> InputReading:
    """One input's reading, with any values the homeowner entered applied over the photo's."""
    entered = entered or {}
    common = dict(kind=kind, used_for=USED_FOR[kind], index=index, entered=entered)
    if provided and result is not None and result.reading is not None:
        # Free-text notes are blanked: they are the one field that could carry stray text.
        photo = {**result.reading.model_dump(mode="json"), "notes": ""}
        reading, disagreements = apply_entered(photo, entered)
        return InputReading(
            **common,
            status="entered" if entered and kind is PhotoKind.GAS_BILL else result.status,
            attempts=result.attempts,
            reading=reading,
            warnings=result.warnings,
            photograph_instead=result.photograph_instead,
            disagreements=disagreements,
        )
    warnings = [] if not provided else ["Gemini couldn't read this right now"]
    if provided and result is not None:
        warnings = result.warnings
    if entered:
        # Nothing read from a photo (none sent, or it couldn't be read): what was entered counts.
        return InputReading(
            **common,
            status="entered",
            attempts=result.attempts if result is not None else 0,
            reading={**entered, "legible": True, "confidence": "medium", "notes": ""},
            warnings=warnings,
            photograph_instead=None,
        )
    return InputReading(
        **common,
        status="couldnt_tell" if provided else "not_provided",
        attempts=result.attempts if result is not None else 0,
        reading=None,
        warnings=warnings,
        photograph_instead=(
            result.photograph_instead
            if result is not None and result.photograph_instead
            else SPECS[kind].photograph_instead
        ),
    )


# Schema fields an entered-only reading has no value for.
_UNREAD = {"radiator_type": "other", "fuel": "unknown", "looks_like": "cutout"}


def _typed[T: Reading](item: InputReading, schema: type[T]) -> T | None:
    """The reading the maths uses (photo values with entered ones applied), as its schema."""
    if item.reading is None or item.status not in (
        "verified",
        "verified_with_warnings",
        "entered",
    ):
        return None
    blank = {
        name: ([] if name == "monthly" else _UNREAD.get(name))
        for name, f in schema.model_fields.items()
        if f.is_required()
    }
    return schema.model_validate({**blank, **item.reading})


def _monthly(bill: GasBillReading) -> dict[int, float] | None:
    """Month-of-year kWh only when they are twelve whole calendar months totalling the bill."""
    if not bill.monthly or bill.period_start is None or bill.period_start.day != 1:
        return None
    try:
        months = bill.kwh_by_calendar_month()
    except ValueError:
        return None
    if set(months) != set(range(1, 13)) or len(bill.monthly) != 12:
        return None
    if not bill.total_kwh or not math.isclose(sum(months.values()), bill.total_kwh, rel_tol=0.01):
        return None
    return months


def _rooms(
    readings: Sequence[tuple[InputReading, RadiatorReading]],
    design_load_kw: float,
    defaults: list[NamedDefault],
) -> list[Room]:
    """Rooms for the radiator check, named by radiator number (never by a homeowner label)."""
    rateable: list[tuple[InputReading, RadiatorReading, float]] = []
    for item, reading in readings:
        if reading.height_mm is None or reading.width_mm is None:
            continue
        per_m2 = c.PANEL_RADIATOR_DT50_W_PER_M2.get(reading.radiator_type)
        if per_m2 is None:
            continue
        rated = per_m2 * reading.height_mm * reading.width_mm / 1e6
        rateable.append((item, reading, rated))
    if not rateable:
        return []
    share = min(c.PHOTOGRAPHED_ROOM_SHARE_OF_HEAT_LOSS, 1.0 / len(rateable))
    loss = design_load_kw * 1000 * share
    rooms: list[Room] = []
    for item, reading, rated in rateable:
        measured = {"height_mm", "width_mm"} & set(item.entered)
        source = (
            "as you measured them"
            if len(measured) == 2
            else "from your measurement and the photo"
            if measured
            else "estimated from the photo"
        )
        defaults.append(
            NamedDefault(
                input="radiators",
                name="radiator_rating_from_photo" if len(measured) < 2 else "radiator_rating",
                value=f"{rated:,.0f} W at ΔT50",
                note=f"Radiator {(item.index or 0) + 1}: {reading.radiator_type} panel, "
                f"{reading.height_mm} x {reading.width_mm} mm {source}, rated from typical "
                "catalogue outputs.",
                confidence="low",
            )
        )
        rooms.append(Room(f"Radiator {(item.index or 0) + 1}", loss, rated))
    defaults.append(
        NamedDefault(
            input="radiators",
            name="photographed_room_share_of_heat_loss",
            value=f"{share:.0%} of {design_load_kw:.1f} kW = {loss:,.0f} W",
            note="No room sizes from one photo: assumes the room is about a fifth of the "
            "house's heat loss. Confirm with a room-by-room survey.",
            confidence="low",
        )
    )
    return rooms


def _epc_defaults(mapping: FabricMapping) -> list[NamedDefault]:
    out = []
    for field, conf in mapping.confidence.items():
        if conf.default:
            value = mapping.fabric_inputs.get(field, mapping.main_heating_fuel)
            out.append(
                NamedDefault(
                    input="epc",
                    name=conf.default,
                    value=str(getattr(value, "value", value)),
                    note=conf.note,
                    confidence=conf.confidence,
                )
            )
    return out


def _epc_summary(raw: dict, mapping: FabricMapping, fuel: HeatingFuel) -> EpcSummary:
    inputs = mapping.fabric_inputs
    return EpcSummary(
        property_type=str(inputs["property_type"])
        if mapping.house_model_supported
        else "unsupported",
        floor_area_m2=inputs["floor_area_m2"],
        storeys=inputs["storeys"],
        age_band=_band_from_note(mapping.confidence["year_built"].note),
        year_built=inputs["year_built"],
        wall_type=str(inputs["wall_type"]),
        glazing=str(inputs["glazing"]),
        loft_insulation_mm=inputs["loft_insulation_mm"],
        floor_insulated=bool(inputs["floor_insulated"]),
        design_outdoor_temp_c=float(inputs["design_outdoor_temp_c"]),
        main_heating_fuel=fuel.value,
        current_energy_efficiency_band=raw.get("current_energy_efficiency_band"),
        walls=descriptions(raw, "walls"),
        roofs=descriptions(raw, "roofs"),
        floors=descriptions(raw, "floors"),
        windows=descriptions(raw, "windows" if "windows" in raw else "window"),
        main_heating=descriptions(raw, "main_heating"),
    )


def _band_from_note(note: str) -> str | None:
    prefix = "Reported band: "
    if note.startswith(prefix):
        return note[len(prefix) :].split(". ")[0]
    return None


def _survey(
    district: str | None,
    epc: EpcSummary,
    readings: list[InputReading],
    bundle: AnalysisBundle,
    basis: str,
    log: list[VerificationLogEntry],
) -> SurveyInput:
    extracted: dict[str, StoredReading] = {}
    for item in readings:
        if item.reading is None:
            continue
        prefix = (
            f"radiators_{item.index + 1}"
            if item.kind is PhotoKind.RADIATORS and item.index
            else item.kind.value
        )
        confidence = item.reading.get("confidence", "low")
        for key, value in item.reading.items():
            if key in ("notes", "confidence", "legible") or value is None:
                continue
            if isinstance(value, list):
                if not value or not all(isinstance(v, str) for v in value):
                    continue
                value = ", ".join(value)
            if isinstance(value, dict):
                continue
            extracted[f"{prefix}_{key}"] = StoredReading(
                value=value, confidence=confidence, evidence=item.status
            )
    return SurveyInput(
        postcode_district=district,
        epc_snapshot=epc.model_dump(mode="json"),
        extracted_readings=extracted,
        estimates={
            "measured": bundle.measured,
            "fabric": bundle.fabric,
            "size_basis": basis,
        },
        cross_check=bundle.cross_check or {},
        cost={"costs_by_flow_temp": bundle.costs_by_flow_temp},
        spec=bundle.target_spec,
        verification_log=[e.model_dump(mode="json") for e in log],
    )
