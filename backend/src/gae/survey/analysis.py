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

import math
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
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
    VerificationLog,
    VerificationLogEntry,
    VerifiedReading,
)
from gae.heatpump import constants as c
from gae.heatpump.constants import HeatingFuel
from gae.heatpump.costs import compare_running_costs
from gae.heatpump.crosscheck import cross_check
from gae.heatpump.measured import MeasuredCaveat, MeasuredEstimate
from gae.heatpump.spec import Room, target_spec
from gae.opendata.bill import DegreeDayProvider, measured_from_bill
from gae.opendata.mapping import FabricMapping, descriptions
from gae.opendata.weather import normalise_postcode
from gae.survey.schemas import (
    AnalysisBundle,
    AnalysisResult,
    EpcSummary,
    Gap,
    InputReading,
    NamedDefault,
    jsonable,
)

COST_FLOW_TEMPS_C = (40, 45, 50, 55)
USED_FOR = {
    PhotoKind.BOILER_PLATE: "heating fuel for the grant; boiler model checked against datasheets",
    PhotoKind.RADIATORS: "radiator check at the target flow temperature",
    PhotoKind.FUSE_CUTOUT: "electricity supply headroom for the all-electric plan",
    PhotoKind.OUTDOOR_SPACE: "whether an outdoor unit fits",
    PhotoKind.GAS_BILL: "Estimate B, measured from what the house actually used",
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
) -> AnalysisResult:
    started = time.monotonic()
    timings: dict[str, int] = {}
    entries: list[VerificationLogEntry] = []
    lock = Lock()

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

    def read(kind: PhotoKind, data: bytes, mime: str) -> VerifiedReading | None:
        try:
            return extract(
                services.gemini, services.datasheets, kind, data, mime, log=LiveLog(kind, record)
            )
        except GeminiError:
            code_log.add(
                "fail", kind, "code", "Gemini call failed", False, "couldn't tell: try again"
            )
            return None

    with ThreadPoolExecutor(max_workers=1 + len(files)) as pool:
        epc_future = pool.submit(timed, "epc", services.epc, certificate_id)
        futures: dict[PhotoKind, Future] = {
            kind: pool.submit(timed, f"read_{kind.value}", read, kind, data, mime)
            for kind, (data, mime) in files.items()
        }
        try:
            raw, mapping = epc_future.result()
        except Exception:
            pool.shutdown(wait=False, cancel_futures=True)
            raise
        verified = {kind: future.result() for kind, future in futures.items()}

    if mapping.estimate is None:
        code_log.add("fail", "epc", "code", "EPC maps to the house heat-loss model", False, "stop")
        raise AnalysisRefused(mapping.reason or "Couldn't tell from this EPC record.")
    fabric = mapping.estimate
    defaults = _epc_defaults(mapping)
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

    gaps: list[Gap] = []
    readings: list[InputReading] = []
    for kind in PhotoKind:
        readings.append(_summary(kind, verified.get(kind), kind in files))
        result = verified.get(kind)
        if kind in files and (result is None or result.status == "couldnt_tell"):
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
    bill = _reading(verified.get(PhotoKind.GAS_BILL), GasBillReading)
    if PhotoKind.GAS_BILL not in files:
        gaps.append(
            Gap(
                input="gas_bill",
                message="No gas bill: no Estimate B, so nothing to check the fabric calc against.",
                provide=f"Add {SPECS[PhotoKind.GAS_BILL].photograph_instead}.",
            )
        )
    elif bill is not None:
        if (
            postcode is None
            or bill.period_start is None
            or bill.period_end is None
            or bill.total_kwh is None
        ):
            gaps.append(
                Gap(
                    input="gas_bill",
                    message="Couldn't tell: the bill period or postcode is missing.",
                    provide="An annual statement showing start and end dates and kWh used.",
                )
            )
        else:
            monthly = _monthly(bill)
            outcome = timed(
                "weather",
                lambda: measured_from_bill(
                    start=bill.period_start,
                    end=bill.period_end,
                    gas_kwh=bill.total_kwh,
                    postcode=postcode,
                    weather_client=services.weather,
                    monthly_gas_kwh=monthly,
                ),
            )
            if outcome.status == "ok" and outcome.estimate is not None:
                measured = outcome.estimate
                annual_gas_kwh = bill.total_kwh
                code_log.add(
                    "check",
                    "gas_bill",
                    "code",
                    f"weather for the exact bill dates: {outcome.weather.days_covered} of "
                    f"{outcome.weather.days_expected} days, "
                    f"{outcome.weather.heating_degree_days:,.0f} degree days",
                    True,
                    "Estimate B from your bill",
                )
                if monthly is None:
                    code_log.add(
                        "check",
                        "gas_bill",
                        "code",
                        "twelve calendar months of kWh for the hot-water baseline",
                        False,
                        "use the named default baseline share and widen the range",
                    )
            else:
                reason = outcome.reason or "Couldn't tell from this bill."
                code_log.add(
                    "fail", "gas_bill", "code", reason, False, "no Estimate B; say what to add"
                )
                gaps.append(
                    Gap(
                        input="gas_bill",
                        message=reason,
                        provide="An annual statement covering exactly 12 months, with dates "
                        "and kWh (a 12-month usage graph from your supplier app also works).",
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
    boiler = _reading(verified.get(PhotoKind.BOILER_PLATE), BoilerPlateReading)
    if fuel is HeatingFuel.OTHER and boiler is not None and boiler.fuel == "natural_gas":
        fuel = HeatingFuel.GAS
        code_log.add("check", "boiler_plate", "code", "fuel from data plate", True, "gas")
    elif boiler is None:
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
    basis = measured.design_load_kw if measured else fabric.design_load_kw
    radiator = _reading(verified.get(PhotoKind.RADIATORS), RadiatorReading)
    rooms = _rooms(radiator, basis.central, defaults)
    if radiator is not None and not rooms:
        gaps.append(
            Gap(
                input="radiators",
                message="Couldn't rate this radiator type from a photo.",
                provide="The radiator's make and model label, or its rated output in watts.",
            )
        )
    check = cross_check(fabric, measured) if measured else None
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
    else:
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
        fabric=jsonable(fabric),
        cross_check=jsonable(check) if check else None,
        costs_by_flow_temp=[jsonable(x) for x in costs],
        target_spec=jsonable(spec),
    )
    epc = _epc_summary(raw, mapping, fuel)

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
        gaps=gaps,
        defaults=defaults,
        log=sorted(entries, key=lambda e: e.at),
        timings_ms=timings,
    )


def _label(kind: PhotoKind) -> str:
    return kind.value.replace("_", " ")


def _reading[T](result: VerifiedReading | None, schema: type[T]) -> T | None:
    if result is None or result.reading is None or not isinstance(result.reading, schema):
        return None
    return result.reading


def _summary(kind: PhotoKind, result: VerifiedReading | None, provided: bool) -> InputReading:
    if not provided:
        return InputReading(
            kind=kind,
            status="not_provided",
            attempts=0,
            reading=None,
            warnings=[],
            photograph_instead=SPECS[kind].photograph_instead,
            used_for=USED_FOR[kind],
        )
    if result is None:
        return InputReading(
            kind=kind,
            status="couldnt_tell",
            attempts=0,
            reading=None,
            warnings=["Gemini couldn't read this right now"],
            photograph_instead=SPECS[kind].photograph_instead,
            used_for=USED_FOR[kind],
        )
    reading = None
    if result.reading is not None:
        # Free-text notes are blanked: they are the one field that could carry stray text.
        reading = {**result.reading.model_dump(mode="json"), "notes": ""}
    return InputReading(
        kind=kind,
        status=result.status,
        attempts=result.attempts,
        reading=reading,
        warnings=result.warnings,
        photograph_instead=result.photograph_instead,
        used_for=USED_FOR[kind],
    )


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
    reading: RadiatorReading | None, design_load_kw: float, defaults: list[NamedDefault]
) -> list[Room]:
    if reading is None or reading.height_mm is None or reading.width_mm is None:
        return []
    per_m2 = c.PANEL_RADIATOR_DT50_W_PER_M2.get(reading.radiator_type)
    if per_m2 is None:
        return []
    rated = per_m2 * reading.height_mm * reading.width_mm / 1e6
    share = c.PHOTOGRAPHED_ROOM_SHARE_OF_HEAT_LOSS
    loss = design_load_kw * 1000 * share
    defaults.append(
        NamedDefault(
            input="radiators",
            name="radiator_rating_from_photo",
            value=f"{rated:,.0f} W at ΔT50",
            note=f"{reading.radiator_type} panel, {reading.height_mm} x {reading.width_mm} mm "
            "estimated from the photo, rated from typical catalogue outputs.",
            confidence="low",
        )
    )
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
    return [Room(reading.room or "Photographed room", loss, rated)]


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
        property_type=str(inputs["property_type"]),
        floor_area_m2=inputs["floor_area_m2"],
        age_band=_band_from_note(mapping.confidence["year_built"].note),
        year_built=inputs["year_built"],
        wall_type=str(inputs["wall_type"]),
        glazing=str(inputs["glazing"]),
        loft_insulation_mm=inputs["loft_insulation_mm"],
        floor_insulated=inputs["floor_insulated"],
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
            extracted[f"{item.kind.value}_{key}"] = StoredReading(
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
