"""Installer emails drafted by gemini-4-argon and checked in code, with the template as fallback.

For each checked quote: (a) code picks two or three right-sized heat pumps from the datasheet
library, (b) Argon writes one polite, technical email from our numbers, the quote checker's flags
and those models, (c) the review's number guard strips every sentence carrying a number we did
not supply, and (d) if too much is stripped, the reply names no library model, or Gemini fails,
the deterministic template is returned instead, so the pack never breaks. Nothing is sent.
"""

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from gae.db.datasheets import DatasheetLookup
from gae.db.models import Datasheet
from gae.gemini.client import GeminiError, StructuredModel, text
from gae.gemini.datasheets import tokens
from gae.gemini.review import NUMBER, SENTENCE, allowed_numbers, supported, tidy
from gae.gemini.schemas import StrippedClaim, VerificationLog
from gae.pack.schemas import (
    ArgonEmail,
    InstallerDraft,
    InstallerDraftsRequest,
    InstallerDraftsResult,
    PackBundle,
    PackQuote,
    SuggestedModel,
)

MODELS_PER_DRAFT = 3
# More than this share of sentences stripped and the draft is no longer the model's email.
MAX_STRIPPED_SHARE = 1 / 3
ADDRESS_PLACEHOLDER = "[your address]"

SYSTEM = (
    "You draft emails for a UK homeowner to send to their own heat pump installer. The homeowner "
    "sends them, not you. Never write a personal name, home address, postcode, account or meter "
    "number: use the placeholders [your name] and [your address]."
)

INSTRUCTIONS = """\
Write one email from the homeowner to the installer who gave QUOTE, asking them to look again.

Rules:
- Use only numbers that appear in HOME, QUOTE or RIGHT_SIZED_MODELS, written as they appear
  there. Never calculate, convert, round differently or invent a number, a price or a date.
  Write counts in words. Money with a thousands comma, e.g. £7,500. No numbered lists.
- Polite, specific and technical: the installer is an expert. Open by thanking them for the
  quote, named by its label exactly. Cite the measured figures in HOME (target size range,
  measured design heat loss, maximum flow temperature; fuse rating if given).
- Raise each flag in QUOTE.flags as a question, using its evidence. Fold in QUOTE.questions.
  Skip info flags unless they help.
- Ask for a re-quote on one or more RIGHT_SIZED_MODELS, naming each by make and model exactly as
  given, and list their datasheet_id in requested_model_ids. Name no other heat pump model. If
  the quoted heat pump is already inside the target range, say so, and ask only for one of them
  to be priced alongside for comparison. If RIGHT_SIZED_MODELS is empty, ask for a re-quote on
  a unit inside the target range, naming no model.
- Say the homeowner is comparing quotes and will decide after hearing back. No pressure, no
  threats, no legal or financial claims.
- Under 220 words. Plain text, short paragraphs. End with "Kind regards," then "[your name]",
  then a line "Property: [your address]".
"""


def right_sized_models(
    lookup: DatasheetLookup, bundle: PackBundle, quote: PackQuote, limit: int = MODELS_PER_DRAFT
) -> list[Datasheet]:
    """Real library heat pumps inside the target range, nearest the central size first.

    The quote's own make leads when the library has it in range (the installer likely fits that
    brand), then one per other make, so the installer gets a choice.
    """
    size = bundle.size_kw
    found = lookup.search_by_spec(min_kw=size.low, max_kw=size.high, kind="heat_pump", limit=20)
    sheets = [
        s
        for s in found
        if s.kind == "heat_pump"
        and s.nominal_capacity_kw is not None
        and size.low <= s.nominal_capacity_kw <= size.high
    ]
    r = quote.reading
    quoted_make = tokens(r.heat_pump_make if r else None)
    quoted = tokens(f"{r.heat_pump_make or ''} {r.heat_pump_model or ''}" if r else None)
    ordered = sorted(
        # The quoted unit itself is no alternative.
        [s for s in sheets if not (quoted and tokens(s.model) <= quoted)],
        key=lambda s: (
            not (quoted_make & tokens(s.make)),
            abs((s.nominal_capacity_kw or 0) - size.central),
            s.id,
        ),
    )
    picked: list[Datasheet] = []
    for sheet in ordered:
        if sheet.make not in {p.make for p in picked}:
            picked.append(sheet)
    picked += [s for s in ordered if s not in picked]
    return picked[:limit]


def _suggested(sheet: Datasheet) -> SuggestedModel:
    return SuggestedModel(
        datasheet_id=sheet.id,
        make=sheet.make,
        model=sheet.model,
        nominal_capacity_kw=sheet.nominal_capacity_kw or 0,
        scop_35=sheet.scop_35,
        source_url=sheet.source_url,
    )


def context(req: InstallerDraftsRequest, quote: PackQuote, models: list[Datasheet]) -> dict:
    """Everything numeric the model may cite for one email, as one JSON document."""
    home = tidy(req.bundle.model_dump(mode="json", exclude_none=True))
    if req.fuse_rating_a is not None:
        home["main_fuse_a"] = req.fuse_rating_a
    return whole(
        {
            "HOME": home,
            "QUOTE": {
                "label": quote.label,
                "reading": quote.reading.model_dump(mode="json", exclude_none=True)
                if quote.reading
                else None,
                "flags": [f.model_dump(mode="json") for f in quote.flags],
                "questions": quote.questions,
            },
            "RIGHT_SIZED_MODELS": [
                {
                    "datasheet_id": s.id,
                    "make": s.make,
                    "model": s.model,
                    "nominal_capacity_kw": s.nominal_capacity_kw,
                    "scop_35": s.scop_35,
                    "scop_55": s.scop_55,
                }
                for s in models
            ],
        }
    )


def whole(node: Any) -> Any:
    """5.0 -> 5, so the model writes "5 kW" and "£14,450", not "5.0 kW" and "£14450.0"."""
    if isinstance(node, float) and node.is_integer():
        return int(node)
    if isinstance(node, dict):
        return {k: whole(v) for k, v in node.items()}
    if isinstance(node, list):
        return [whole(v) for v in node]
    return node


def guard(
    where: str, value: str, allowed: list[float], stripped: list[StrippedClaim]
) -> tuple[str, int]:
    """The review's number check, line by line so the email keeps its paragraphs.

    Returns the kept text and how many sentences there were.
    """
    lines: list[str] = []
    total = 0
    for line in value.strip().splitlines():
        kept = []
        for sentence in SENTENCE.split(line.strip()):
            if not sentence:
                continue
            total += 1
            bad = [n for n in NUMBER.findall(sentence) if not supported(n, allowed)]
            if bad:
                stripped.append(StrippedClaim(where=where, text=sentence, numbers=bad))
            else:
                kept.append(sentence)
        if kept or not line.strip():
            lines.append(" ".join(kept))
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip(), total


def names_model(body: str, sheet: Datasheet) -> bool:
    """Most of the catalogue model's tokens, including a size or variant code, are in the text."""
    wanted = tokens(sheet.model)
    found = wanted & tokens(body)
    has_code = any(any(ch.isdigit() for ch in t) for t in found)
    return bool(wanted) and has_code and len(found) / len(wanted) >= 0.6


def _kw(value: float) -> str:
    return f"{round(value, 1):g}"


def _range(r: Any, unit: str) -> str:
    return f"{_kw(r.low)}-{_kw(r.high)} {unit} (central {_kw(r.central)})"


def template(req: InstallerDraftsRequest, quote: PackQuote, models: list[Datasheet]) -> str:
    """The deterministic draft: same facts, no model, nothing to check."""
    b = req.bundle
    lines = [
        "Hello,",
        "",
        f"Thank you for your quote ({quote.label}). Before I decide, I have checked it against "
        "my home's own numbers and would like to ask a few questions.",
        "",
        "For this home our numbers suggest:",
        f"- Target heat pump size: {_range(b.size_kw, 'kW')}",
        f"- Maximum design flow temperature: {_kw(b.max_flow_temp_c)} °C",
    ]
    if b.measured_design_load_kw:
        lines.append(
            f"- Measured design heat loss (from my gas bills): "
            f"{_range(b.measured_design_load_kw, 'kW')}"
        )
    if b.htc_w_per_k:
        lines.append(f"- Heat transfer coefficient: {_range(b.htc_w_per_k, 'W/K')}")
    if req.fuse_rating_a is not None:
        lines.append(f"- Main fuse: {req.fuse_rating_a} A")
    r = quote.reading
    if r and (r.heat_pump_kw is not None or r.design_flow_temp_c is not None):
        lines += ["", "About your quote:"]
        if r.heat_pump_kw is not None:
            unit = " ".join(p for p in (r.heat_pump_make, r.heat_pump_model) if p)
            unit = f"{unit}, " if unit else ""
            lines.append(f"- Quoted heat pump: {unit}{_kw(r.heat_pump_kw)} kW")
        if r.design_flow_temp_c is not None:
            lines.append(f"- Design flow temperature: {_kw(r.design_flow_temp_c)} °C")
    concerns = [f for f in quote.flags if f.severity != "info"]
    if concerns:
        lines += ["", "A second-opinion check flagged:"]
        lines += [f"- {f.message} ({f.evidence})" for f in concerns]
    if quote.questions:
        lines += ["", "Could you answer these?"]
        lines += [f"- {q}" for q in quote.questions]
    if models:
        lines += [
            "",
            "Could you also re-quote on a right-sized heat pump, for example one of these "
            "(from a public datasheet library)?",
        ]
        lines += [f"- {s.make} {s.model} ({_kw(s.nominal_capacity_kw or 0)} kW)" for s in models]
    lines += [
        "",
        "I am comparing quotes and will decide once I have heard back.",
        "",
        "Kind regards,",
        "[your name]",
        f"Property: {ADDRESS_PLACEHOLDER}",
    ]
    return "\n".join(lines)


def template_subject(quote: PackQuote) -> str:
    return f"Questions and a re-quote request about your quote ({quote.label})"


def draft_one(
    gemini: StructuredModel, req: InstallerDraftsRequest, quote: PackQuote, models: list[Datasheet]
) -> InstallerDraft:
    started = time.monotonic()
    log = VerificationLog()
    where = quote.label
    size = req.bundle.size_kw
    log.add(
        "check",
        where,
        "code",
        f"datasheet library: {len(models)} heat pumps inside {_kw(size.low)}-{_kw(size.high)} kW",
        bool(models),
        ", ".join(s.id for s in models) or "none in range: draft asks for a right-sized unit",
    )
    ctx = context(req, quote, models)
    allowed = allowed_numbers(ctx)

    def fallback(reason: str, stripped: list[StrippedClaim] | None = None) -> InstallerDraft:
        log.add("fail", where, "code", reason, False, "use the template draft")
        return InstallerDraft(
            quote_label=quote.label,
            source="template",
            subject=template_subject(quote),
            text=template(req, quote, models),
            stripped=stripped or [],
            models=[_suggested(s) for s in models],
            fallback_reason=reason,
            elapsed_ms=round((time.monotonic() - started) * 1000),
            log=log.entries,
        )

    try:
        email = gemini.generate(
            model=gemini.lead_model,
            input=[text(INSTRUCTIONS), text(json.dumps(ctx, indent=1, ensure_ascii=False))],
            schema=ArgonEmail,
            # Medium, not high: this is writing from numbers already checked in code, not
            # reasoning over photos, and the code guard below catches any number it gets wrong.
            # Medium keeps each draft to seconds rather than the review's minutes.
            thinking_level="medium",
            system_instruction=SYSTEM,
            timeout_s=120,
        )
    except GeminiError:
        return fallback("Gemini couldn't draft this right now")
    log.add("read", where, gemini.lead_model, "draft installer email", True, "check numbers")

    stripped: list[StrippedClaim] = []
    subject, _ = guard("subject", email.subject, allowed, stripped)
    body, total = guard("body", email.body, allowed, stripped)
    for claim in stripped:
        log.add(
            "check",
            where,
            "code",
            f"numbers {', '.join(claim.numbers)} in the {claim.where} not in our figures",
            False,
            "removed sentence",
        )
    removed = len([c for c in stripped if c.where == "body"])
    if total == 0 or removed > total * MAX_STRIPPED_SHARE:
        return fallback(f"{removed} of {total} sentences had untraceable numbers", stripped)

    by_id = {s.id: s for s in models}
    unknown = [i for i in email.requested_model_ids if i not in by_id]
    named = [by_id[i] for i in dict.fromkeys(email.requested_model_ids) if i in by_id]
    named = [s for s in named if names_model(body, s)]
    log.add(
        "check",
        where,
        "code",
        "re-quote asks for a right-sized model from our datasheet library",
        (bool(named) or not models) and not unknown,
        ", ".join(s.id for s in named) or "none named",
    )
    if models and not named:
        return fallback("the draft didn't name a right-sized model from our library", stripped)

    if ADDRESS_PLACEHOLDER not in body:
        body += f"\nProperty: {ADDRESS_PLACEHOLDER}"
    log.add(
        "pass" if not stripped else "check",
        where,
        "code",
        "every number traced to our figures, your quote or the datasheets",
        not stripped,
        "show draft" if not stripped else f"removed {len(stripped)} sentence(s), show the rest",
    )
    return InstallerDraft(
        quote_label=quote.label,
        source="argon",
        subject=subject or template_subject(quote),
        text=body,
        stripped=stripped,
        models=[_suggested(s) for s in named],
        elapsed_ms=round((time.monotonic() - started) * 1000),
        log=log.entries,
    )


def draft_installer_emails(
    gemini: StructuredModel, lookup: DatasheetLookup, req: InstallerDraftsRequest
) -> InstallerDraftsResult:
    models = [right_sized_models(lookup, req.bundle, q) for q in req.quotes]
    # One independent email per quote: draft them together so three take one draft's time.
    with ThreadPoolExecutor(max_workers=len(req.quotes)) as pool:
        drafts = list(
            pool.map(lambda qm: draft_one(gemini, req, *qm), zip(req.quotes, models, strict=True))
        )
    return InstallerDraftsResult(drafts=drafts, model=gemini.lead_model)
