"""Gemini reads each input; code checks the reading; a failed check goes back once.

Model choice per input:
- Photos of plates, radiators, cutouts and outdoor space start on the fast model: a few
  printed fields or a rough size, where Flash is accurate and keeps the upload flow snappy.
- Gas bills and installer quotes start on the lead model: multi-page tables, date ranges and
  priced line items, where a misread propagates into Estimate B or a quote flag.
- Every re-read uses the lead model at high thinking with the failed check spelled out,
  so the second look is the most careful one rather than a repeat of the first.
"""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass

from gae.db.datasheets import DatasheetLookup
from gae.gemini import checks
from gae.gemini.client import Block, StructuredModel, ThinkingLevel, document, image, text
from gae.gemini.sanitize import sanitize_image
from gae.gemini.schemas import (
    BoilerPlateReading,
    FuseCutoutReading,
    GasBillReading,
    OutdoorSpaceReading,
    PhotoCheckResult,
    PhotoGlance,
    PhotoKind,
    QuoteReading,
    RadiatorReading,
    Reading,
    VerificationLog,
    VerifiedReading,
)

SYSTEM = (
    "You read homeowner photos and documents for a UK heat-pump survey. Report only what is "
    "visible. Use null for anything you cannot read and never guess a number. Never transcribe "
    "or describe people, faces, vehicle number plates, house numbers, street names or signs, "
    "postal mail or envelopes, personal names, home addresses, supplier account numbers or "
    "gas or electricity meter numbers — even if they are clearly visible."
)


@dataclass(frozen=True)
class Spec:
    schema: type[Reading]
    lead_first: bool
    thinking: ThinkingLevel
    prompt: str
    photograph_instead: str
    check: Callable[[Reading, DatasheetLookup], checks.Outcome]


SPECS: dict[str, Spec] = {
    PhotoKind.BOILER_PLATE: Spec(
        BoilerPlateReading,
        lead_first=False,
        thinking="medium",
        prompt=(
            "This should be a gas boiler's data plate. Read make, model, GC number, maximum "
            "central-heating output (kW) and, for a combi, hot-water output (kW)."
        ),
        photograph_instead=(
            "the data plate itself, straight on and in focus: it is usually behind the "
            "boiler's lower flap or on the side of the casing"
        ),
        check=lambda r, lookup: checks.check_boiler(r, lookup),
    ),
    PhotoKind.RADIATORS: Spec(
        RadiatorReading,
        lead_first=False,
        thinking="medium",
        prompt=(
            "This should be a radiator. Identify its type by counting panels and convector fin "
            "rows (look from above or at the side), and estimate height and width in mm using "
            "nearby objects such as skirting boards, sockets or doors for scale."
        ),
        photograph_instead=(
            "the whole radiator from the front with a tape measure across it, plus one shot "
            "looking down between the panels"
        ),
        check=lambda r, lookup: checks.check_radiator(r),
    ),
    PhotoKind.FUSE_CUTOUT: Spec(
        FuseCutoutReading,
        lead_first=False,
        thinking="medium",
        prompt=(
            "This should be the electricity supplier's service cutout (the sealed fuse carrier "
            "before the meter). Read the main fuse rating in amps, often printed on the carrier "
            "or a label. Say what the photo actually shows."
        ),
        photograph_instead=(
            "the sealed fuse carrier next to the electricity meter, close enough to read the "
            "number on it (e.g. 60, 80 or 100): not the meter, not the consumer unit"
        ),
        check=lambda r, lookup: checks.check_fuse(r),
    ),
    PhotoKind.OUTDOOR_SPACE: Spec(
        OutdoorSpaceReading,
        lead_first=False,
        thinking="medium",
        prompt=(
            "This should be the outdoor spot for a heat pump unit. Estimate the clear width and "
            "depth in metres using bricks, fence panels or doors for scale, the surface, and "
            "obstructions such as drains, windows or steps."
        ),
        photograph_instead=(
            "the spot from a few steps back so the wall, ground and neighbouring windows are "
            "all in frame, ideally with a tape measure laid out"
        ),
        check=lambda r, lookup: checks.check_outdoor(r),
    ),
    PhotoKind.GAS_BILL: Spec(
        GasBillReading,
        lead_first=True,
        thinking="medium",
        prompt=(
            "This should be a UK gas bill or annual statement. Read the supplier, the period "
            "start and end dates, the gas used in kWh over that period (kWh, not £ and not "
            "cubic metres), any month-by-month kWh figures, and whether readings are estimated."
        ),
        photograph_instead=(
            "your annual gas statement, or the page of a bill that shows kWh used and the "
            "period dates; a 12-month usage graph from your supplier app also works"
        ),
        check=lambda r, lookup: checks.check_bill(r),
    ),
    "quote": Spec(
        QuoteReading,
        lead_first=True,
        thinking="medium",
        prompt=(
            "This is an installer's heat pump quote. Read the heat pump make, model and kW, "
            "the design flow temperature, whether a buffer tank is included, the hot-water "
            "cylinder, every priced line item, the final total, whether the Boiler Upgrade "
            "Scheme grant is deducted and how much, and the MCS heat loss figure if stated."
        ),
        photograph_instead=(
            "the full quote PDF including the itemised price page and the technical page "
            "with heat loss and flow temperature"
        ),
        check=lambda r, lookup: checks.check_quote(r, lookup),
    ),
}

GLANCE_HINTS = {
    PhotoKind.BOILER_PLATE: "make, model, output_kw",
    PhotoKind.RADIATORS: "radiator_type, panels",
    PhotoKind.FUSE_CUTOUT: "rating_a",
    PhotoKind.OUTDOOR_SPACE: "rough_size_m, surface",
    PhotoKind.GAS_BILL: "supplier, kwh, period",
}


def media(data: bytes, mime_type: str) -> Block:
    if mime_type == "application/pdf":
        return document(data)
    if mime_type.startswith("image/"):
        data, mime_type = sanitize_image(data, mime_type)
        return image(data, mime_type)
    raise ValueError("Upload a photo (JPEG, PNG, HEIC, WebP) or a PDF")


def glance(
    gemini: StructuredModel, kind: PhotoKind, data: bytes, mime_type: str
) -> PhotoCheckResult:
    """Instant check on upload: fast model, low thinking, a few seconds at most."""
    started = time.monotonic()
    result = gemini.generate(
        model=gemini.fast_model,
        input=[
            text(
                f"The homeowner says this is a photo of: {kind.value.replace('_', ' ')}. "
                f"Say what it actually shows, whether the key details are legible, and list "
                f"only key fields you can already read ({GLANCE_HINTS[kind]}). If it is not "
                f"usable give one short retake instruction. Flag any visible face, vehicle "
                f"number plate, house number, street name or sign, letter or envelope, or any "
                f"personal name, home address, account number or meter number (do not transcribe "
                f"those into key_fields)."
            ),
            media(data, mime_type),
        ],
        schema=PhotoGlance,
        thinking_level="low",
        system_instruction=SYSTEM,
        timeout_s=15,
    )
    matches = result.detected_kind == kind.value
    usable = matches and result.legible
    hint = result.retake_hint
    if not usable and not hint:
        hint = f"Retake: photograph {SPECS[kind].photograph_instead}."
    privacy = None
    flags = (
        ("a face", result.face_visible),
        ("a vehicle number plate", result.number_plate_visible),
        ("a house number or street sign", result.house_or_street_visible),
        ("post or an envelope", result.mail_or_envelope_visible),
        (
            "a name, address, account number or meter number",
            result.name_address_or_meter_visible,
        ),
    )
    if any(f for _, f in flags):
        seen = " and ".join(what for what, flag in flags if flag)
        privacy = (
            f"This photo may show {seen}. Cover it and resend; only the redacted image "
            f"is sent to Gemini and we never store photos."
        )
    return PhotoCheckResult(
        kind=result.detected_kind,
        expected_kind=kind,
        matches_expected=matches,
        legible=result.legible,
        usable=usable,
        summary=result.summary,
        key_fields={f.name: f.value for f in result.key_fields},
        confidence=result.confidence,
        retake_hint=None if usable else hint,
        privacy_warning=privacy,
        model=gemini.fast_model,
        elapsed_ms=round((time.monotonic() - started) * 1000),
    )


def _reread_prompt(spec: Spec, reading: Reading, failed: list[checks.Check]) -> str:
    problems = "\n".join(f"- {c.name}: {c.detail}" for c in failed)
    return (
        f"{spec.prompt}\n\nA previous reading of this same input was:\n"
        f"{reading.model_dump_json()}\n\nCode checks on that reading failed:\n{problems}\n\n"
        "Look again carefully at exactly these points. If the input genuinely does not show "
        "them clearly, set legible to false and leave the values null rather than guessing."
    )


def extract(
    gemini: StructuredModel,
    lookup: DatasheetLookup,
    kind: str,
    data: bytes,
    mime_type: str,
    *,
    media_parts: list[tuple[bytes, str]] | None = None,
    log: VerificationLog | None = None,
) -> VerifiedReading:
    """Read, check, re-read once on failure, then verify or give up with a retake hint.

    Pass `log` to watch entries as they are added (the survey streams them to the UI).
    """
    spec = SPECS[kind]
    parts = [(data, mime_type)]
    if media_parts:
        parts.extend(media_parts)
    blocks = [media(part[0], part[1]) for part in parts]
    log = VerificationLog() if log is None else log
    reading: Reading | None = None
    outcome: checks.Outcome | None = None
    failed: list[checks.Check] = []
    for attempt in (1, 2):
        first = attempt == 1
        model = gemini.lead_model if (spec.lead_first or not first) else gemini.fast_model
        thinking: ThinkingLevel = spec.thinking if first else "high"
        prompt = spec.prompt if first else _reread_prompt(spec, reading, failed)
        if first and kind == "quote" and len(parts) > 1:
            prompt = (
                f"{prompt}\n\nThese {len(parts)} images are sequential pages of one installer "
                "quote. Read them together as a single document."
            )
        reading = gemini.generate(
            model=model,
            input=[text(prompt), *blocks],
            schema=spec.schema,
            thinking_level=thinking,
            system_instruction=SYSTEM,
            timeout_s=90 if spec.lead_first or not first else 30,
        )
        log.add(
            "read" if first else "reread",
            kind,
            model,
            "Gemini reads the input" if first else "Gemini re-reads with the failed checks",
            True,
            _summarise(reading),
        )
        outcome = spec.check(reading, lookup)
        failed = [c for c in outcome.checks if not c.passed]
        for c in outcome.checks:
            if c.passed:
                action = "ok"
            elif first:
                action = "ask Gemini to look again"
            else:
                action = "couldn't tell" if c.hard else "keep reading, show as a warning"
            log.add("check", kind, "code", f"{c.name}: {c.detail}", c.passed, action)
        if not failed:
            log.add("pass", kind, "code", "all checks passed", True, "use this reading")
            return VerifiedReading[spec.schema](
                kind=kind,
                status="verified",
                reading=reading,
                attempts=attempt,
                warnings=[],
                photograph_instead=None,
                datasheet_id=outcome.datasheet_id,
                log=log.entries,
            )
    hard = [c for c in failed if c.hard]
    if hard:
        log.add(
            "fail",
            kind,
            "code",
            "; ".join(c.name for c in hard),
            False,
            f"couldn't tell: photograph {spec.photograph_instead}",
        )
        return VerifiedReading[spec.schema](
            kind=kind,
            status="couldnt_tell",
            reading=None,
            attempts=2,
            warnings=[f"{c.name}: {c.detail}" for c in failed],
            photograph_instead=spec.photograph_instead,
            log=log.entries,
        )
    log.add("pass", kind, "code", "hard checks passed", True, "use this reading with warnings")
    return VerifiedReading[spec.schema](
        kind=kind,
        status="verified_with_warnings",
        reading=reading,
        attempts=2,
        warnings=[f"{c.name}: {c.detail}" for c in failed],
        photograph_instead=None,
        datasheet_id=outcome.datasheet_id,
        log=log.entries,
    )


def _summarise(reading: Reading) -> str:
    """Short log line of the values read, without notes or free text."""
    values = reading.model_dump(mode="json", exclude={"notes", "line_items", "monthly"})
    shown = {k: v for k, v in values.items() if v is not None and v != []}
    return json.dumps(shown, separators=(", ", ": "))[:300]
