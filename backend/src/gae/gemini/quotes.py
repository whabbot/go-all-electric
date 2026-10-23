"""Quote flags computed in code from a verified quote reading and the maths-core size range.

Gemini only reads the quote; every flag and number here comes from code, so the quote checker
works (and stays honest) even before the one-context review runs.
"""

from dataclasses import dataclass

from gae.gemini.schemas import QuoteCheckResult, QuoteFlag, QuoteReading, VerifiedReading

# Above this design flow temperature running costs rise noticeably (see heatpump.costs).
HIGH_FLOW_TEMP_C = 50
GOOD_FLOW_TEMP_C = 45


@dataclass(frozen=True)
class SizeContext:
    """From the maths core: target size range and measured design load, all kW."""

    size_low_kw: float
    size_high_kw: float
    design_load_kw: float | None = None


def flag_quote(
    filename: str, verified: VerifiedReading[QuoteReading], size: SizeContext | None
) -> QuoteCheckResult:
    flags: list[QuoteFlag] = []
    questions: list[str] = []
    r = verified.reading
    if r is None:
        flags.append(
            QuoteFlag(
                severity="amber",
                message="Couldn't read this quote reliably",
                evidence=f"Upload {verified.photograph_instead}.",
            )
        )
        return QuoteCheckResult(
            filename=filename,
            quoted_kw=None,
            design_flow_temp_c=None,
            flags=flags,
            questions_to_ask=[],
            verified=verified,
        )

    kw = r.heat_pump_kw
    if kw is not None and size is not None:
        about = f"{size.design_load_kw:.1f}" if size.design_load_kw else f"{size.size_low_kw:g}"
        if kw > size.size_high_kw:
            flags.append(
                QuoteFlag(
                    severity="red",
                    message=f"{kw:g} kW quoted, your bills suggest about {about} kW: oversized",
                    evidence=f"Target size range {size.size_low_kw:g}-{size.size_high_kw:g} kW "
                    "from your measured gas use.",
                )
            )
            questions.append(
                "Your heat loss survey: which rooms and what air change rate gave this size?"
            )
        elif kw < size.size_low_kw:
            flags.append(
                QuoteFlag(
                    severity="amber",
                    message=f"{kw:g} kW quoted, below the {size.size_low_kw:g} kW lower bound",
                    evidence=f"Target size range {size.size_low_kw:g}-{size.size_high_kw:g} kW.",
                )
            )
            questions.append("How will this unit cope on the coldest design day?")
        else:
            flags.append(
                QuoteFlag(
                    severity="info",
                    message=f"{kw:g} kW is inside your target range",
                    evidence=f"Target size range {size.size_low_kw:g}-{size.size_high_kw:g} kW.",
                )
            )

    stated_loss = r.mcs_heat_loss_kw
    if stated_loss is not None and size and size.design_load_kw and stated_loss > size.size_high_kw:
        flags.append(
            QuoteFlag(
                severity="amber",
                message=f"Quoted heat loss {stated_loss:g} kW is above what your bills show "
                f"(about {size.design_load_kw:.1f} kW)",
                evidence="MCS heat loss figure on the quote vs measured design load.",
            )
        )
        questions.append("Can I see the room-by-room heat loss calculation?")

    flow = r.design_flow_temp_c
    if flow is not None:
        if flow > HIGH_FLOW_TEMP_C:
            flags.append(
                QuoteFlag(
                    severity="amber",
                    message=f"Design flow {flow:g}°C: expect higher bills",
                    evidence="Efficiency (SCOP) falls as flow temperature rises.",
                )
            )
            questions.append(
                f"Which radiators would need upsizing to run at {GOOD_FLOW_TEMP_C}°C or below?"
            )
        elif flow <= GOOD_FLOW_TEMP_C:
            flags.append(
                QuoteFlag(
                    severity="info",
                    message=f"Design flow {flow:g}°C: good for running costs",
                    evidence="Low flow temperature keeps SCOP high.",
                )
            )

    if r.buffer_tank:
        flags.append(
            QuoteFlag(
                severity="amber",
                message="Buffer tank: ask why",
                evidence="Most well-designed systems do not need one; it can cut efficiency.",
            )
        )
        questions.append("Why is a buffer tank needed, and what does it do to efficiency?")

    if r.grant_deducted is False:
        flags.append(
            QuoteFlag(
                severity="red",
                message="Grant not deducted",
                evidence="The Boiler Upgrade Scheme grant should be taken off the price you pay.",
            )
        )
        questions.append("Will you apply for the Boiler Upgrade Scheme grant and deduct it?")
    elif r.grant_deducted is None:
        questions.append("Is the Boiler Upgrade Scheme grant already deducted from this price?")

    for warning in verified.warnings:
        if warning.startswith("quoted kW matches the datasheet"):
            flags.append(
                QuoteFlag(
                    severity="amber",
                    message="Quoted kW doesn't match the manufacturer's datasheet",
                    evidence=warning.split(": ", 1)[1],
                )
            )
            questions.append("Which exact model is this, and what is its rated output?")

    return QuoteCheckResult(
        filename=filename,
        quoted_kw=kw,
        design_flow_temp_c=flow,
        flags=flags,
        questions_to_ask=questions,
        verified=verified,
    )
