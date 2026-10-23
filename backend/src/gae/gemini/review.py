"""One gemini-4-argon context reviews everything together, then code checks its numbers.

Photos, bill, EPC record, full datasheets for every matched model, all quotes and the maths-core
outputs go into a single high-thinking interaction. The model explains and flags; it does not
calculate. Afterwards every number it wrote is matched against the numbers we gave it, and
any sentence carrying a number we cannot trace is removed and reported (a second loop).
"""

import base64
import json
import re
from typing import Any

from gae.db.datasheets import DatasheetLookup
from gae.db.models import Datasheet
from gae.gemini.client import Block, StructuredModel, text
from gae.gemini.datasheets import match_datasheet
from gae.gemini.extract import SYSTEM, media
from gae.gemini.schemas import (
    ArgonReview,
    QuoteReview,
    ReviewFlag,
    ReviewRequest,
    ReviewResult,
    StrippedClaim,
    VerificationLog,
)

# Digits not glued to a preceding letter, so model codes like "R290" or "WZ50VAA" are skipped.
NUMBER = re.compile(r"(?<![A-Za-z0-9.])\d[\d,]*(?:\.\d+)?")
SENTENCE = re.compile(r"(?<=[.!?])\s+")
# A UK postcode, full or outward code with a space, anywhere in a string.
POSTCODE = re.compile(r"\b[A-Z]{1,2}[0-9][A-Z0-9]?\s*[0-9][A-Z]{2}\b", re.IGNORECASE)

# The only EPC fields Gemini sees: the building, never where it is or whose it is.
EPC_BUILDING_FIELDS = (
    "schema_type",
    "assessment_type",
    "total_floor_area",
    "floor_area_m2",
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
them and to review the installer quotes against them and the evidence.

Rules:
- Use only numbers that appear in MATHS, the EPC record, the readings, the datasheets or the
  quotes. Never calculate, round differently or invent a number. Write counts in words.
- Estimate A is the fabric (installer-style) heat loss; Estimate B is measured from gas bills.
  Explain why they differ using the cross-check reasons in MATHS.cross_check.reasons, most
  important first, and list their codes in cited_reason_codes. Do not smooth over the gap.
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


def review(gemini: StructuredModel, lookup: DatasheetLookup, req: ReviewRequest) -> ReviewResult:
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
    )
    log.add("read", "review", gemini.lead_model, "one-context review", True, "check numbers")
    cleaned, stripped = verify_numbers(raw, allowed_numbers(context), req, log)
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
        "READINGS": {
            "boiler": req.boiler.model_dump(mode="json") if req.boiler else None,
            "gas_bill": req.bill_reading.model_dump(mode="json") if req.bill_reading else None,
        },
        "QUOTES": [
            {
                "quote_id": q.quote_id,
                "reading": q.reading.model_dump(mode="json") if q.reading else None,
            }
            for q in req.quotes
        ],
        "DATASHEETS": [s.model_dump(mode="json", exclude={"text"}) for s in sheets],
    }


def building_fields(record: dict[str, Any]) -> dict[str, Any]:
    """Allowlisted building fields only; nested identifying keys and postcodes are dropped."""

    def scrub(node: Any) -> Any:
        if isinstance(node, dict):
            return {
                k: scrub(v)
                for k, v in node.items()
                if not any(part in str(k).lower() for part in _IDENTIFYING_KEY_PARTS)
            }
        if isinstance(node, list):
            return [scrub(v) for v in node]
        if isinstance(node, str) and POSTCODE.search(node):
            return None
        return node

    return {key: scrub(record[key]) for key in EPC_BUILDING_FIELDS if key in record}


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
) -> tuple[ArgonReview, list[StrippedClaim]]:
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
    return (
        ArgonReview(
            estimates_explanation=explanation,
            cited_reason_codes=codes,
            quote_reviews=quote_reviews,
            questions_to_ask=questions,
            summary=summary,
        ),
        stripped,
    )
