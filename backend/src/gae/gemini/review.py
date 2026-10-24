"""One gemini-4-argon context reviews everything together, then code checks its numbers and
tests its conflict proposals.

Photos, bill, EPC record, full datasheets for every matched model, all verified readings, all
quotes and the maths-core outputs go into a single high-thinking interaction. The model explains,
flags, and proposes which EPC field or fabric assumption may be wrong; it does not calculate.
Code verifies every conflict proposal against the closed field/value enums and provided evidence,
re-runs `estimate_fabric` with each single correction to test whether the A-vs-B gap shrinks, and
strips any sentence carrying a number that cannot be traced to the inputs.
"""

import base64
import json
import math
import re
from typing import Any

from gae.db.datasheets import DatasheetLookup
from gae.db.models import Datasheet
from gae.gemini.client import Block, StructuredModel, text
from gae.gemini.datasheets import match_datasheet
from gae.gemini.extract import SYSTEM, media
from gae.gemini.schemas import (
    ALLOWED_VALUES_BY_FIELD,
    ArgonReview,
    ConflictField,
    ConflictStatus,
    EstimateDirection,
    EvidenceSource,
    InputConflictProposal,
    PhotoKind,
    ProposedValue,
    QuoteReview,
    RangePayload,
    ReviewFlag,
    ReviewRequest,
    ReviewResult,
    StrippedClaim,
    TestedConflict,
    VerificationLog,
)
from gae.heatpump import constants as c
from gae.heatpump.fabric import (
    EXPOSED_WALL_FRACTION,
    FabricEstimate,
    Glazing,
    PropertyType,
    WallType,
    estimate_fabric,
)

BASELINE_REL_TOL = 0.01

# Digits not glued to a preceding letter, so model codes like "R290" or "WZ50VAA" are skipped.
NUMBER = re.compile(r"(?<![A-Za-z0-9.])\d[\d,]*(?:\.\d+)?")
SENTENCE = re.compile(r"(?<=[.!?])\s+")
# A UK postcode, full or outward code with a space, anywhere in a string.
POSTCODE = re.compile(r"\b[A-Z]{1,2}[0-9][A-Z0-9]?\s*[0-9][A-Z]{2}\b", re.IGNORECASE)
CERTIFICATE_ID = re.compile(r"\b\d{4}-\d{4}-\d{4}-\d{4}-\d{4}\b")

# The only EPC fields Gemini sees: the building, never where it is or whose it is.
EPC_BUILDING_FIELDS = (
    "schema_type",
    "assessment_type",
    "total_floor_area",
    "floor_area_m2",
    "storeys",
    "dwelling_type",
    "property_type",
    "built_form",
    "construction_age_band",
    "age_band",
    "year_built",
    "walls",
    "roofs",
    "floors",
    "window",
    "windows",
    "glazing",
    "wall_type",
    "loft_insulation_mm",
    "floor_insulated",
    "design_outdoor_temp_c",
    "indoor_temp_c",
    "main_heating",
    "main_heating_fuel",
    "current_energy_efficiency_band",
    "current_energy_efficiency_rating",
    "potential_energy_efficiency_band",
    "potential_energy_efficiency_rating",
)
_IDENTIFYING_KEY_PARTS = ("address", "postcode", "uprn", "certificate", "lmk", "name", "town")

INSTRUCTIONS = """\
You are giving a homeowner a second opinion on going from a gas boiler to a heat pump.
All calculations are already done in code and given to you as MATHS. Your job is to explain
them, propose which EPC or fabric assumption may be wrong when the evidence points to a conflict,
and review the installer quotes against them and the evidence.

Rules:
- Use only numbers that appear in MATHS, the EPC record, the readings, the datasheets or the
  quotes. Never calculate, round differently or invent a number. Write counts in words.
- Estimate A is the fabric (installer-style) heat loss; Estimate B is measured from gas bills.
  Explain why they differ using the cross-check reasons in MATHS.cross_check.reasons, most
  important first, and list their codes in cited_reason_codes. Do not smooth over the gap.
- Input conflict proposals (`conflict_status` and `input_conflicts`):
  Look across all provided evidence (photos, boiler_plate, gas_bill, fuse_cutout, radiators,
  radiator_video, outdoor_space, loft, quote, epc) to see whether an EPC building field or
  fabric-model assumption feeding Estimate A is probably wrong or outdated.
  If no conflict is supported by the provided evidence, set `conflict_status` to
  `no_conflict_found` and `input_conflicts` to `[]`.
  If the evidence suggests one or more conflicts, set `conflict_status` to `conflicts_found` and
  propose each in `input_conflicts` so code can re-run Estimate A with that single correction:
  - `field`: one of `wall_type`, `loft_insulation_mm`, `glazing`, `floor_insulated`,
    `air_change_rate`, `property_type`, `storeys`.
  - `evidence_source`: only an input present in this run (`boiler_plate`, `gas_bill`,
    `fuse_cutout`, `radiators`, `radiator_video`, `outdoor_space`, `loft`, `quote`, `epc`).
    For `loft_insulation_mm`, `loft` is the expected `evidence_source` when a loft photo or
    reading is provided.
  - `evidence_summary`: plain English saying what that evidence shows in words (never invent
    numbers).
  - `proposed_value`: choose only from the closed set for that `field`:
    * `wall_type`: `solid_brick`, `cavity_unfilled`, `cavity_filled`, `solid_insulated`,
      `timber_frame`
    * `loft_insulation_mm`: `0mm`, `25mm`, `50mm`, `100mm`, `150mm`, `200mm`, `270mm`
    * `glazing`: `single`, `double_unknown_date`, `double_pre_2003`, `double_2003_onwards`,
      `triple`
    * `floor_insulated`: `insulated`, `uninsulated`
    * `air_change_rate`: `1.0_ach`, `1.5_ach`
    * `property_type`: `detached`, `semi_detached`, `end_terrace`, `mid_terrace`, `bungalow`
    * `storeys`: `1_storey`, `2_storeys`, `3_storeys`
  - `expected_direction`: `lower` or `higher` for how Estimate A should move.
- For each quote, flag concerns (severity info, amber or red) with the evidence each rests on:
  size against MATHS.target_spec.size_kw, design flow temperature against running costs in
  MATHS.costs_by_flow_temp, buffer tanks, grant deduction, datasheet mismatches, heat loss.
  Refer to quotes by their quote_id exactly.
- questions_to_ask: short questions the homeowner can put to installers.
- The homeowner reads this on a phone: keep estimates_explanation under 120 words, each flag
  to one or two sentences, and the summary to two sentences. Plain English, no field names.
- This is a second opinion, not financial advice: say what the evidence shows; the homeowner
  decides.
"""


def review(
    gemini: StructuredModel,
    lookup: DatasheetLookup,
    req: ReviewRequest,
    *,
    purpose: str = "/api/review",
) -> ReviewResult:
    log = VerificationLog()
    sheets = _datasheets(lookup, req)
    log.add(
        "check",
        "datasheets",
        "code",
        f"datasheet library: {len(sheets)} full datasheets attached",
        True,
        ", ".join(s.id for s in sheets) or "none matched",
    )
    context = _context(req, sheets)
    raw = gemini.generate(
        model=gemini.lead_model,
        input=_input(req, context, sheets),
        schema=ArgonReview,
        thinking_level="high",
        system_instruction=SYSTEM,
        timeout_s=600,
        purpose=purpose,
    )
    log.add("read", "review", gemini.lead_model, "one-context review", True, "check numbers")
    cleaned, stripped, tested_conflicts = verify_numbers(raw, allowed_numbers(context), req, log)
    log.add(
        "pass" if not stripped else "fail",
        "review",
        "code",
        "every number traced to our calculations or your documents",
        not stripped,
        "show review" if not stripped else f"removed {len(stripped)} unverified statement(s)",
    )
    return ReviewResult(
        review=cleaned,
        tested_conflicts=tested_conflicts,
        stripped=stripped,
        datasheets_used=[s.id for s in sheets],
        model=gemini.lead_model,
        log=log.entries,
    )


def _datasheets(lookup: DatasheetLookup, req: ReviewRequest) -> list[Datasheet]:
    found: dict[str, Datasheet] = {}
    if req.boiler:
        sheet = match_datasheet(
            lookup, req.boiler.make, req.boiler.model, {"gas_combi", "gas_system"}
        )
        if sheet:
            found[sheet.id] = sheet
    for quote in req.quotes:
        if quote.reading:
            r = quote.reading
            sheet = match_datasheet(lookup, r.heat_pump_make, r.heat_pump_model, {"heat_pump"})
            if sheet:
                found[sheet.id] = sheet
    # Right-sized alternatives give the reviewer a reference point for oversized quotes.
    size = req.maths.target_spec.get("size_kw")
    if isinstance(size, dict):
        for sheet in lookup.search_by_spec(
            min_kw=_float(size.get("low")), max_kw=_float(size.get("high")), limit=3
        ):
            found.setdefault(sheet.id, sheet)
    return list(found.values())


def _float(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) else None


def _context(req: ReviewRequest, sheets: list[Datasheet]) -> dict[str, Any]:
    """Everything numeric the model may cite, as one JSON document."""
    return {
        "MATHS": tidy(req.maths.model_dump(mode="json")),
        "EPC": building_fields(req.epc_record),
        "READINGS": _scrub_privacy(
            {
                "boiler": req.boiler.model_dump(mode="json") if req.boiler else None,
                "gas_bill": req.bill_reading.model_dump(mode="json") if req.bill_reading else None,
                "radiators": (
                    [r.model_dump(mode="json") for r in req.radiators] or None
                    if isinstance(req.radiators, list)
                    else req.radiators.model_dump(mode="json")
                    if req.radiators
                    else None
                ),
                "radiator_video": (
                    req.radiator_video.model_dump(mode="json", exclude={"log"})
                    if req.radiator_video
                    else None
                ),
                "fuse_cutout": (
                    req.fuse_cutout.model_dump(mode="json") if req.fuse_cutout else None
                ),
                "outdoor_space": (
                    req.outdoor_space.model_dump(mode="json") if req.outdoor_space else None
                ),
                "loft": req.loft.model_dump(mode="json") if req.loft else None,
            }
        ),
        "QUOTES": _scrub_privacy(
            [
                {
                    "quote_id": q.quote_id,
                    "reading": q.reading.model_dump(mode="json") if q.reading else None,
                }
                for q in req.quotes
            ]
        ),
        "DATASHEETS": [s.model_dump(mode="json", exclude={"text"}) for s in sheets],
    }


def _scrub_privacy(node: Any) -> Any:
    if isinstance(node, dict):
        return {
            k: _scrub_privacy(v)
            for k, v in node.items()
            if not any(part in str(k).lower() for part in _IDENTIFYING_KEY_PARTS)
        }
    if isinstance(node, list):
        return [_scrub_privacy(v) for v in node]
    if isinstance(node, str) and (POSTCODE.search(node) or CERTIFICATE_ID.search(node)):
        return None
    return node


def building_fields(record: dict[str, Any]) -> dict[str, Any]:
    """Allowlisted building fields only; nested identifying keys and postcodes are dropped."""
    return {key: _scrub_privacy(record[key]) for key in EPC_BUILDING_FIELDS if key in record}


def _input(req: ReviewRequest, context: dict[str, Any], sheets: list[Datasheet]) -> list[Block]:
    blocks: list[Block] = [text(INSTRUCTIONS), text(json.dumps(context, indent=1))]
    for sheet in sheets:
        blocks.append(text(f"FULL DATASHEET {sheet.id}:\n{sheet.text}"))
    for i, photo in enumerate(req.photos, 1):
        blocks.append(text(f"PHOTO {i}: {photo.kind}"))
        blocks.append(media(base64.b64decode(photo.data_base64), photo.mime_type))
    if req.bill:
        blocks.append(text("GAS BILL:"))
        blocks.append(media(base64.b64decode(req.bill.data_base64), req.bill.mime_type))
    for quote in req.quotes:
        if quote.document:
            blocks.append(text(f"QUOTE {quote.quote_id}:"))
            for page in (quote.document, *quote.pages):
                blocks.append(media(base64.b64decode(page.data_base64), page.mime_type))
    return blocks


def tidy(node: Any) -> Any:
    """Round maths outputs to the precision a homeowner reads, so the model quotes them so."""
    if isinstance(node, float):
        return round(node) if abs(node) >= 100 else round(node, 1 if abs(node) >= 10 else 2)
    if isinstance(node, dict):
        return {k: tidy(v) for k, v in node.items()}
    if isinstance(node, list):
        return [tidy(v) for v in node]
    return node


def allowed_numbers(context: Any) -> list[float]:
    """Every number in the context, plus percentages of fractions and kW of watt values."""
    out: set[float] = set()

    def walk(node: Any, key: str = "") -> None:
        if isinstance(node, bool) or node is None:
            return
        if isinstance(node, int | float):
            value = abs(float(node))
            out.add(value)
            if 0 < value < 1:
                out.add(value * 100)
            if key.endswith("_w"):
                out.add(value / 1000)
        elif isinstance(node, str):
            out.update(_parse(n) for n in NUMBER.findall(node))
        elif isinstance(node, dict):
            for k, v in node.items():
                walk(k, "")
                walk(v, str(k))
        elif isinstance(node, list | tuple):
            for v in node:
                walk(v, key)

    walk(context)
    return sorted(out)


def _parse(token: str) -> float:
    return float(token.replace(",", ""))


def supported(token: str, allowed: list[float]) -> bool:
    """Does a number as written match a context value, to the precision it was written at?

    "4.7" matches 4.716; "1,200" matches 1,213 (rounded to tens or hundreds); "5" matches 4.6.
    """
    value = _parse(token)
    digits = token.replace(",", "")
    if "." in digits:
        tolerance = 0.5 * 10 ** -len(digits.split(".")[1])
    else:
        trailing = len(digits) - len(digits.rstrip("0"))
        tolerance = 0.5 * 10**trailing if value >= 1000 and trailing else 0.5
    return any(abs(value - a) <= tolerance + 1e-9 for a in allowed)


def _clean(where: str, value: str, allowed: list[float], stripped: list[StrippedClaim]) -> str:
    kept = []
    for sentence in SENTENCE.split(value.strip()):
        bad = [n for n in NUMBER.findall(sentence) if not supported(n, allowed)]
        if bad:
            stripped.append(StrippedClaim(where=where, text=sentence, numbers=bad))
        elif sentence:
            kept.append(sentence)
    return " ".join(kept)


def verify_numbers(
    review: ArgonReview, allowed: list[float], req: ReviewRequest, log: VerificationLog
) -> tuple[ArgonReview, list[StrippedClaim], list[TestedConflict]]:
    stripped: list[StrippedClaim] = []
    explanation = _clean("estimates_explanation", review.estimates_explanation, allowed, stripped)
    if not explanation:
        explanation = (
            "The explanation could not be verified against our calculations; see the "
            "cross-check reasons instead."
        )

    known = set(req.maths.reason_codes())
    codes = [c for c in review.cited_reason_codes if c.value in known]
    unknown = [c.value for c in review.cited_reason_codes if c.value not in known]
    log.add(
        "check",
        "review",
        "code",
        "cited reasons come from the cross-check",
        not unknown,
        "ok" if not unknown else f"dropped {', '.join(unknown)}",
    )

    cleaned_conflicts, tested_conflicts = verify_conflicts(review, allowed, stripped, req, log)

    quote_ids = {q.quote_id for q in req.quotes}
    quote_reviews = []
    for qr in review.quote_reviews:
        if qr.quote_id not in quote_ids:
            log.add("check", "review", "code", f"quote {qr.quote_id} exists", False, "dropped")
            continue
        flags = []
        for i, flag in enumerate(qr.flags):
            where = f"quote_reviews[{qr.quote_id}].flags[{i}]"
            message = _clean(where, flag.message, allowed, stripped)
            evidence = _clean(where + ".evidence", flag.evidence, allowed, stripped)
            if message:
                flags.append(ReviewFlag(severity=flag.severity, message=message, evidence=evidence))
        quote_reviews.append(QuoteReview(quote_id=qr.quote_id, flags=flags))

    questions = [
        q
        for i, question in enumerate(review.questions_to_ask)
        if (q := _clean(f"questions_to_ask[{i}]", question, allowed, stripped))
    ]
    summary = _clean("summary", review.summary, allowed, stripped)
    for claim in stripped:
        log.add(
            "check",
            "review",
            "code",
            f"numbers {', '.join(claim.numbers)} in {claim.where} not in our calculations",
            False,
            "removed statement",
        )
    conflict_status = (
        ConflictStatus.CONFLICTS_FOUND if cleaned_conflicts else ConflictStatus.NO_CONFLICT_FOUND
    )
    return (
        ArgonReview(
            estimates_explanation=explanation,
            cited_reason_codes=codes,
            conflict_status=conflict_status,
            input_conflicts=cleaned_conflicts,
            quote_reviews=quote_reviews,
            questions_to_ask=questions,
            summary=summary,
        ),
        stripped,
        tested_conflicts,
    )


def verify_conflicts(
    review: ArgonReview,
    allowed: list[float],
    stripped: list[StrippedClaim],
    req: ReviewRequest,
    log: VerificationLog,
) -> tuple[list[InputConflictProposal], list[TestedConflict]]:
    """Validate proposed conflicts against closed enums and evidence, then re-run fabric."""
    if not review.input_conflicts:
        log.add(
            "check",
            "conflicts",
            "code",
            "input conflict proposals",
            True,
            "no conflict proposed",
        )
        return [], []

    baseline = _baseline_fabric_inputs(req)
    baseline_est = _reproduce_baseline_fabric(req, baseline)
    cleaned_proposals: list[InputConflictProposal] = []
    tested: list[TestedConflict] = []

    for i, proposal in enumerate(review.input_conflicts):
        raw_field = str(proposal.field)
        try:
            field = ConflictField(raw_field)
        except ValueError:
            log.add(
                "check",
                "conflicts",
                "code",
                f"conflict field '{raw_field}' is a valid fabric input",
                False,
                "rejected unknown field",
            )
            continue

        raw_source = str(proposal.evidence_source)
        try:
            source = EvidenceSource(raw_source)
        except ValueError:
            log.add(
                "check",
                "conflicts",
                "code",
                f"conflict on {field.value}: evidence source '{raw_source}' is known",
                False,
                "rejected unknown evidence source",
            )
            continue

        if not _evidence_present(req, source):
            log.add(
                "check",
                "conflicts",
                "code",
                f"conflict on {field.value}: {source.value} evidence was provided",
                False,
                f"rejected ({source.value} not provided in this run)",
            )
            continue

        raw_value = str(proposal.proposed_value)
        value = _parse_proposed_value(field, raw_value)
        if value is None or value not in ALLOWED_VALUES_BY_FIELD[field]:
            log.add(
                "check",
                "conflicts",
                "code",
                f"conflict on {field.value}: value '{raw_value}' in closed set",
                False,
                "rejected value outside closed set",
            )
            continue

        raw_direction = str(proposal.expected_direction)
        try:
            direction = EstimateDirection(raw_direction)
        except ValueError:
            log.add(
                "check",
                "conflicts",
                "code",
                f"conflict on {field.value}: direction '{raw_direction}' is valid",
                False,
                "rejected invalid direction",
            )
            continue

        if baseline_est is None:
            log.add(
                "check",
                "conflicts",
                "code",
                (
                    f"re-run fabric.py with {field.value}={value.value}: "
                    "baseline reproduces Estimate A"
                ),
                False,
                "could not reproduce Estimate A",
            )
            continue

        where = f"input_conflicts[{i}].evidence_summary"
        summary_text = _clean(where, proposal.evidence_summary, allowed, stripped)
        if not summary_text:
            summary_text = "See the provided survey evidence for this input."

        result = _test_single_conflict(
            req=req,
            baseline=baseline,
            baseline_est=baseline_est,
            field=field,
            source=source,
            summary_text=summary_text,
            value=value,
            direction=direction,
        )
        cleaned_proposals.append(
            InputConflictProposal(
                field=field,
                evidence_source=source,
                evidence_summary=summary_text,
                proposed_value=value,
                expected_direction=direction,
            )
        )
        tested.append(result)
        log.add(
            "check",
            "conflicts",
            "code",
            f"re-run fabric.py with {field.value}={value.value} (evidence: {source.value})",
            True,
            (
                f"Estimate A {result.original_design_load_kw.central:.1f} -> "
                f"{result.new_design_load_kw.central:.1f} kW; A-vs-B gap {result.gap_change}"
            ),
        )

    return cleaned_proposals, tested


def _evidence_present(req: ReviewRequest, source: EvidenceSource) -> bool:
    photo_kinds = {p.kind for p in req.photos}
    if source == EvidenceSource.BOILER_PLATE:
        return req.boiler is not None or PhotoKind.BOILER_PLATE in photo_kinds
    if source == EvidenceSource.GAS_BILL:
        return (
            req.bill_reading is not None
            or req.bill is not None
            or PhotoKind.GAS_BILL in photo_kinds
        )
    if source == EvidenceSource.FUSE_CUTOUT:
        return req.fuse_cutout is not None or PhotoKind.FUSE_CUTOUT in photo_kinds
    if source == EvidenceSource.RADIATORS:
        return bool(req.radiators) or PhotoKind.RADIATORS in photo_kinds
    if source == EvidenceSource.RADIATOR_VIDEO:
        return req.radiator_video is not None
    if source == EvidenceSource.OUTDOOR_SPACE:
        return req.outdoor_space is not None or PhotoKind.OUTDOOR_SPACE in photo_kinds
    if source == EvidenceSource.LOFT:
        return req.loft is not None or PhotoKind.LOFT in photo_kinds
    if source == EvidenceSource.QUOTE:
        return bool(req.quotes)
    if source == EvidenceSource.EPC:
        return bool(building_fields(req.epc_record))
    return False


_VALUE_ALIASES: dict[tuple[ConflictField, str], ProposedValue] = {
    (ConflictField.LOFT_INSULATION_MM, "0"): ProposedValue.LOFT_0MM,
    (ConflictField.LOFT_INSULATION_MM, "25"): ProposedValue.LOFT_25MM,
    (ConflictField.LOFT_INSULATION_MM, "50"): ProposedValue.LOFT_50MM,
    (ConflictField.LOFT_INSULATION_MM, "100"): ProposedValue.LOFT_100MM,
    (ConflictField.LOFT_INSULATION_MM, "150"): ProposedValue.LOFT_150MM,
    (ConflictField.LOFT_INSULATION_MM, "200"): ProposedValue.LOFT_200MM,
    (ConflictField.LOFT_INSULATION_MM, "270"): ProposedValue.LOFT_270MM,
    (ConflictField.FLOOR_INSULATED, "true"): ProposedValue.INSULATED,
    (ConflictField.FLOOR_INSULATED, "false"): ProposedValue.UNINSULATED,
    (ConflictField.AIR_CHANGE_RATE, "1.0"): ProposedValue.ACH_1_0,
    (ConflictField.AIR_CHANGE_RATE, "1.5"): ProposedValue.ACH_1_5,
    (ConflictField.STOREYS, "1"): ProposedValue.STOREYS_1,
    (ConflictField.STOREYS, "2"): ProposedValue.STOREYS_2,
    (ConflictField.STOREYS, "3"): ProposedValue.STOREYS_3,
}


def _parse_proposed_value(field: ConflictField, raw: str) -> ProposedValue | None:
    cleaned = raw.strip().lower()
    if (field, cleaned) in _VALUE_ALIASES:
        return _VALUE_ALIASES[(field, cleaned)]
    try:
        return ProposedValue(cleaned)
    except ValueError:
        return None


def _baseline_fabric_inputs(req: ReviewRequest) -> dict[str, Any]:
    """Extract `estimate_fabric` arguments from `epc_record` or reconstruct from `maths.fabric`.

    Prefers the exact building fields passed in `epc_record` (`EpcSummary` from the analysis)
    and always supplies `floor_insulated` explicitly as a `bool` so toggling `year_built` for
    `air_change_rate` cannot alter floor insulation.
    """
    fabric = req.maths.fabric
    epc = req.epc_record

    epc_area = _float(epc.get("floor_area_m2")) or _float(epc.get("total_floor_area"))
    volume_m3 = _float(fabric.get("volume_m3"))
    if epc_area and epc_area > 0:
        floor_area_m2 = epc_area
    elif volume_m3 and volume_m3 > 0:
        floor_area_m2 = round(volume_m3 / c.ROOM_HEIGHT_M, 2)
    else:
        floor_area_m2 = 90.0

    raw_prop = epc.get("property_type")
    epc_prop: PropertyType | None = None
    if isinstance(raw_prop, str):
        try:
            epc_prop = PropertyType(raw_prop)
        except ValueError:
            epc_prop = None

    roof_area_m2 = _float(fabric.get("roof_area_m2")) or (floor_area_m2 / 2)
    raw_storeys = epc.get("storeys")
    if isinstance(raw_storeys, int) and not isinstance(raw_storeys, bool) and raw_storeys >= 1:
        storeys = raw_storeys
    elif roof_area_m2 > 0:
        storeys = max(1, round(floor_area_m2 / roof_area_m2))
    else:
        storeys = 1 if epc_prop is PropertyType.BUNGALOW else 2

    net_wall = _float(fabric.get("net_wall_area_m2"))
    if epc_prop is not None:
        property_type = epc_prop
    elif net_wall is not None and roof_area_m2 > 0:
        window_area = _float(fabric.get("window_area_m2")) or (
            floor_area_m2 * c.WINDOW_TO_FLOOR_RATIO
        )
        door_area = c.DOOR_AREA_M2 * c.DOORS_PER_DWELLING
        gross_wall = net_wall + window_area + door_area
        denom = 4 * math.sqrt(roof_area_m2) * c.STOREY_HEIGHT_M * storeys
        target_fraction = gross_wall / denom if denom > 0 else 0.75
        candidates = [
            pt
            for pt in PropertyType
            if (pt is PropertyType.BUNGALOW) == (storeys == 1 and target_fraction > 0.9)
        ] or list(PropertyType)
        property_type = min(
            candidates,
            key=lambda pt: abs(EXPOSED_WALL_FRACTION[pt] - target_fraction),
        )
    else:
        property_type = PropertyType.SEMI_DETACHED

    raw_year = epc.get("year_built")
    built_before_2000 = fabric.get("built_before_2000")
    if isinstance(raw_year, int) and not isinstance(raw_year, bool):
        year_built = raw_year
    elif isinstance(built_before_2000, bool):
        year_built = 1930 if built_before_2000 else 2005
    else:
        year_built = 1930

    raw_wall = str(
        epc.get("wall_type") or fabric.get("wall_type") or WallType.CAVITY_UNFILLED.value
    )
    try:
        wall_type = WallType(raw_wall)
    except ValueError:
        wall_type = WallType.CAVITY_UNFILLED

    raw_glazing = str(
        epc.get("glazing") or fabric.get("glazing") or Glazing.DOUBLE_UNKNOWN_DATE.value
    )
    try:
        glazing = Glazing(raw_glazing)
    except ValueError:
        glazing = Glazing.DOUBLE_UNKNOWN_DATE

    raw_loft = epc.get("loft_insulation_mm")
    if isinstance(raw_loft, bool) or not isinstance(raw_loft, int | float):
        raw_loft = fabric.get("loft_insulation_mm")
    loft_insulation_mm = (
        int(raw_loft)
        if isinstance(raw_loft, int | float) and not isinstance(raw_loft, bool)
        else 100
    )

    raw_floor_ins = epc.get("floor_insulated")
    elements = fabric.get("element_w_per_k")
    floor_w_per_k = _float(elements.get("floor")) if isinstance(elements, dict) else None
    if isinstance(raw_floor_ins, bool):
        floor_insulated = raw_floor_ins
    elif floor_w_per_k is not None and roof_area_m2 > 0:
        floor_insulated = abs(floor_w_per_k / roof_area_m2 - c.FLOOR_U_INSULATED) < 0.05
    else:
        floor_insulated = bool(year_built >= 2003)

    design_outdoor_temp_c = _float(epc.get("design_outdoor_temp_c"))
    if design_outdoor_temp_c is None:
        design_outdoor_temp_c = _float(req.maths.measured.get("design_outdoor_temp_c"))
    if design_outdoor_temp_c is None:
        design_outdoor_temp_c = c.LONDON_DESIGN_OUTDOOR_TEMP_C

    indoor_temp_c = _float(epc.get("indoor_temp_c"))
    if indoor_temp_c is None:
        indoor_temp_c = _float(req.maths.measured.get("indoor_temp_c"))
    if indoor_temp_c is None:
        indoor_temp_c = c.DESIGN_INDOOR_TEMP_C

    return {
        "floor_area_m2": floor_area_m2,
        "storeys": storeys,
        "property_type": property_type,
        "year_built": year_built,
        "wall_type": wall_type,
        "glazing": glazing,
        "loft_insulation_mm": loft_insulation_mm,
        "floor_insulated": bool(floor_insulated),
        "indoor_temp_c": indoor_temp_c,
        "design_outdoor_temp_c": design_outdoor_temp_c,
    }


def _reproduce_baseline_fabric(
    req: ReviewRequest, baseline: dict[str, Any]
) -> FabricEstimate | None:
    """Run `estimate_fabric(**baseline)` and confirm it reproduces headline Estimate A within 1%."""
    try:
        baseline_est = estimate_fabric(**baseline)
    except TypeError, ValueError:
        return None

    headline_htc = _extract_range_central(req.maths.fabric.get("htc_w_per_k"))
    headline_load = _extract_range_central(req.maths.fabric.get("design_load_kw"))
    if headline_htc is None or headline_htc <= 0 or headline_load is None or headline_load <= 0:
        return None

    if not math.isclose(baseline_est.htc_w_per_k.central, headline_htc, rel_tol=BASELINE_REL_TOL):
        return None
    if not math.isclose(
        baseline_est.design_load_kw.central, headline_load, rel_tol=BASELINE_REL_TOL
    ):
        return None
    return baseline_est


def _extract_range_central(node: Any) -> float | None:
    if isinstance(node, int | float) and not isinstance(node, bool):
        return float(node)
    if isinstance(node, dict):
        return _float(node.get("central"))
    return None


def _test_single_conflict(
    req: ReviewRequest,
    baseline: dict[str, Any],
    baseline_est: FabricEstimate,
    field: ConflictField,
    source: EvidenceSource,
    summary_text: str,
    value: ProposedValue,
    direction: EstimateDirection,
) -> TestedConflict:
    updated = dict(baseline)
    updated["floor_insulated"] = bool(baseline["floor_insulated"])
    if field == ConflictField.WALL_TYPE:
        current_value = baseline["wall_type"].value
        updated["wall_type"] = WallType(value.value)
    elif field == ConflictField.LOFT_INSULATION_MM:
        current_value = f"{baseline['loft_insulation_mm']}mm"
        updated["loft_insulation_mm"] = int(value.value.removesuffix("mm"))
    elif field == ConflictField.GLAZING:
        current_value = baseline["glazing"].value
        updated["glazing"] = Glazing(value.value)
    elif field == ConflictField.FLOOR_INSULATED:
        current_value = (
            ProposedValue.INSULATED.value
            if baseline["floor_insulated"]
            else ProposedValue.UNINSULATED.value
        )
        updated["floor_insulated"] = value == ProposedValue.INSULATED
    elif field == ConflictField.AIR_CHANGE_RATE:
        current_value = (
            ProposedValue.ACH_1_5.value
            if baseline["year_built"] < 2000
            else ProposedValue.ACH_1_0.value
        )
        updated["year_built"] = 2001 if value == ProposedValue.ACH_1_0 else 1930
    elif field == ConflictField.PROPERTY_TYPE:
        current_value = baseline["property_type"].value
        updated["property_type"] = PropertyType(value.value)
    elif field == ConflictField.STOREYS:
        s = baseline["storeys"]
        current_value = f"{s}_storey" if s == 1 else f"{s}_storeys"
        updated["storeys"] = int(value.value.split("_", 1)[0])
    else:
        current_value = "unknown"

    rerun = estimate_fabric(**updated)
    original_load = RangePayload.from_range(baseline_est.design_load_kw)
    new_load = RangePayload.from_range(rerun.design_load_kw)
    original_htc = round(baseline_est.htc_w_per_k.central, 2)
    new_htc = round(rerun.htc_w_per_k.central, 2)

    if direction == EstimateDirection.LOWER:
        direction_matches = rerun.htc_w_per_k.central < baseline_est.htc_w_per_k.central - 1e-6
    else:
        direction_matches = rerun.htc_w_per_k.central > baseline_est.htc_w_per_k.central + 1e-6

    measured_htc = _extract_range_central(req.maths.measured.get("htc_w_per_k"))
    measured_kw = _extract_range_central(req.maths.measured.get("design_load_kw"))

    if measured_htc is not None:
        raw_orig_gap = abs(baseline_est.htc_w_per_k.central - measured_htc)
        raw_new_gap = abs(rerun.htc_w_per_k.central - measured_htc)
        original_gap_w_per_k = round(raw_orig_gap, 2)
        new_gap_w_per_k = round(raw_new_gap, 2)
        original_gap_kw = (
            round(abs(baseline_est.design_load_kw.central - measured_kw), 2)
            if measured_kw is not None
            else None
        )
        new_gap_kw = (
            round(abs(rerun.design_load_kw.central - measured_kw), 2)
            if measured_kw is not None
            else None
        )
        if abs(raw_new_gap - raw_orig_gap) < 1e-6:
            gap_change: Any = "unchanged"
        elif raw_new_gap < raw_orig_gap:
            gap_change = "shrinks"
        else:
            gap_change = "grows"
    else:
        original_gap_w_per_k = None
        new_gap_w_per_k = None
        original_gap_kw = None
        new_gap_kw = None
        gap_change = "unchanged"

    return TestedConflict(
        field=field,
        evidence_source=source,
        evidence_summary=summary_text,
        current_value=current_value,
        proposed_value=value,
        expected_direction=direction,
        direction_matches=direction_matches,
        original_design_load_kw=original_load,
        new_design_load_kw=new_load,
        original_htc_w_per_k=original_htc,
        new_htc_w_per_k=new_htc,
        original_gap_kw=original_gap_kw,
        new_gap_kw=new_gap_kw,
        original_gap_w_per_k=original_gap_w_per_k,
        new_gap_w_per_k=new_gap_w_per_k,
        gap_change=gap_change,
    )
