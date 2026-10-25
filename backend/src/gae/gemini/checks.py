"""Deterministic checks on each Gemini reading. Code, not the model, decides what is plausible.

A failed check of either kind triggers one re-read. After the re-read, a failed *hard* check
means "couldn't tell"; a failed *soft* check keeps the reading and becomes a warning.
"""

from dataclasses import dataclass

from gae.db.datasheets import DatasheetLookup
from gae.gemini.datasheets import match_datasheet
from gae.gemini.schemas import (
    ALLOWED_VALUES_BY_FIELD,
    BoilerPlateReading,
    ConflictField,
    FuseCutoutReading,
    GasBillReading,
    LoftReading,
    OutdoorSpaceReading,
    QuoteReading,
    RadiatorReading,
)

# Main service fuse ratings fitted in UK homes.
STANDARD_FUSE_RATINGS_A = {40, 45, 60, 63, 80, 100}
ALLOWED_LOFT_DEPTH_BANDS = {
    v.value for v in ALLOWED_VALUES_BY_FIELD[ConflictField.LOFT_INSULATION_MM]
}
# Annual gas use, kWh: below this the home is barely gas-heated; above it, likely misread.
PLAUSIBLE_ANNUAL_GAS_KWH = (2_000, 40_000)
FULL_YEAR_DAYS = (300, 430)  # about 10 to 14 months
QUOTE_SUM_TOLERANCE_GBP = 1.0
# Panels and fin rows implied by each radiator type.
RADIATOR_SHAPES = {"single_panel": (1, 0), "K1": (1, 1), "P+": (2, 1), "K2": (2, 2), "K3": (3, 3)}


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str
    hard: bool = True


@dataclass(frozen=True)
class Outcome:
    checks: list[Check]
    datasheet_id: str | None = None


def _legible(reading, what: str) -> Check:
    return Check(
        f"{what} legible",
        reading.legible,
        "readable" if reading.legible else f"model reports it cannot read the {what}",
    )


def check_boiler(r: BoilerPlateReading, lookup: DatasheetLookup) -> Outcome:
    checks = [_legible(r, "data plate")]
    checks.append(
        Check(
            "make and model read",
            bool(r.make and r.model),
            f"{r.make} {r.model}" if r.make and r.model else "make or model missing",
        )
    )
    kw = r.heating_output_kw
    checks.append(
        Check(
            "heating output plausible (3-70 kW)",
            kw is not None and 3 <= kw <= 70,
            f"{kw} kW" if kw is not None else "no output figure read",
        )
    )
    sheet = match_datasheet(lookup, r.make, r.model, {"gas_combi", "gas_system"})
    checks.append(
        Check(
            "model found in datasheet library",
            sheet is not None,
            f"matched {sheet.make} {sheet.model}" if sheet else "no library entry matches",
            hard=False,
        )
    )
    if sheet and kw is not None:
        low = (sheet.heating_min_kw or 0) * 0.9
        high = max(sheet.nominal_capacity_kw or 0, sheet.heating_max_kw or 0) * 1.1
        checks.append(
            Check(
                "plate output within catalogue range",
                low <= kw <= high,
                f"plate {kw} kW vs catalogue {low:.1f}-{high:.1f} kW",
            )
        )
    return Outcome(checks, sheet.id if sheet else None)


def check_bill(r: GasBillReading) -> Outcome:
    checks = [_legible(r, "bill")]
    total = r.total_kwh
    checks.append(Check("gas kWh read", total is not None and total > 0, f"{total} kWh"))
    days = None
    if r.period_start and r.period_end:
        days = (r.period_end - r.period_start).days + 1
    checks.append(
        Check(
            "billing period read",
            days is not None and days > 0,
            f"{r.period_start} to {r.period_end}" if days else "start or end date missing",
        )
    )
    if total and days and days > 0:
        annual = total * 365 / days
        low, high = PLAUSIBLE_ANNUAL_GAS_KWH
        checks.append(
            Check(
                "kWh plausible for a UK home",
                (low <= total <= high) if 365 <= days <= 366 else 0 < total <= high,
                f"about {annual:,.0f} kWh a year (expect {low:,}-{high:,})",
            )
        )
        checks.append(
            Check(
                "12 months in a row gives the best estimate",
                FULL_YEAR_DAYS[0] <= days <= FULL_YEAR_DAYS[1],
                f"{days} days" + ("" if days >= FULL_YEAR_DAYS[0] else ": partial year"),
                hard=False,
            )
        )
    if r.monthly and total:
        summed = sum(m.kwh for m in r.monthly)
        checks.append(
            Check(
                "monthly figures add up to the total",
                abs(summed - total) <= 0.05 * total,
                f"months sum to {summed:,.0f} kWh vs total {total:,.0f} kWh",
                hard=False,
            )
        )
    return Outcome(checks)


def check_fuse(r: FuseCutoutReading) -> Outcome:
    return Outcome(
        [
            _legible(r, "fuse carrier"),
            Check(
                "photo shows the service cutout",
                r.looks_like == "cutout",
                "cutout" if r.looks_like == "cutout" else f"this looks like the {r.looks_like}",
            ),
            Check(
                "standard fuse rating",
                r.rating_a in STANDARD_FUSE_RATINGS_A,
                f"{r.rating_a} A" if r.rating_a else "no rating read",
            ),
        ]
    )


def check_radiator(r: RadiatorReading) -> Outcome:
    h, w = r.height_mm, r.width_mm
    checks = [
        _legible(r, "radiator"),
        Check(
            "size plausible (250-2000 mm tall, 300-3000 mm wide)",
            h is not None and w is not None and 250 <= h <= 2000 and 300 <= w <= 3000,
            f"{h} x {w} mm",
        ),
    ]
    shape = RADIATOR_SHAPES.get(r.radiator_type)
    if shape:
        checks.append(
            Check(
                "panels and fins match the type",
                (r.panels, r.fin_rows) == shape,
                f"{r.radiator_type} should be {shape[0]} panel(s), {shape[1]} fin row(s); "
                f"read {r.panels}, {r.fin_rows}",
                hard=False,
            )
        )
    return Outcome(checks)


def check_outdoor(r: OutdoorSpaceReading) -> Outcome:
    w, d = r.clear_width_m, r.clear_depth_m
    checks = [_legible(r, "outdoor space")]
    sized = w is not None and d is not None
    checks.append(
        Check(
            "clear space sized",
            sized,
            f"{w} x {d} m" if sized else "could not judge size",
            hard=False,
        )
    )
    if sized:
        checks.append(
            Check("size plausible (0.3-30 m)", 0.3 <= w <= 30 and 0.3 <= d <= 30, f"{w} x {d} m")
        )
        checks.append(
            Check(
                "room for a typical monobloc (1.0 x 0.6 m plus clearance)",
                w >= 1.0 and d >= 0.6,
                f"{w} x {d} m",
                hard=False,
            )
        )
    return Outcome(checks)


def check_loft(r: LoftReading) -> Outcome:
    checks = [
        _legible(r, "loft insulation"),
        Check(
            "insulation visible in photo",
            r.insulation_visible is True,
            "insulation visible" if r.insulation_visible else "insulation not clearly visible",
        ),
        Check(
            "depth band in allowed set",
            r.depth_mm_band in ALLOWED_LOFT_DEPTH_BANDS,
            r.depth_mm_band or "no depth band read",
        ),
    ]
    if (
        r.joists_visible_above_insulation is not None
        and r.depth_mm_band in ALLOWED_LOFT_DEPTH_BANDS
    ):
        consistent = not (
            (r.depth_mm_band in {"200mm", "270mm"} and r.joists_visible_above_insulation is True)
            or (r.depth_mm_band == "0mm" and r.joists_visible_above_insulation is False)
        )
        checks.append(
            Check(
                "joist visibility consistent with depth band",
                consistent,
                f"depth {r.depth_mm_band}, joists visible={r.joists_visible_above_insulation}",
                hard=False,
            )
        )
    return Outcome(checks)


def quote_sum_matches(r: QuoteReading) -> tuple[bool, str]:
    """Line items add to the total, allowing for a grant taken off below the line."""
    summed = sum(item.amount_gbp for item in r.line_items)
    total = r.total_gbp or 0.0
    detail = f"items sum to £{summed:,.2f} vs total £{total:,.2f}"
    if abs(summed - total) <= QUOTE_SUM_TOLERANCE_GBP:
        return True, detail
    has_grant_line = any(item.amount_gbp < 0 for item in r.line_items)
    if r.grant_deducted and r.grant_amount_gbp and not has_grant_line:
        after_grant = summed - r.grant_amount_gbp
        if abs(after_grant - total) <= QUOTE_SUM_TOLERANCE_GBP:
            return True, f"{detail} after £{r.grant_amount_gbp:,.0f} grant"
    return False, detail


def check_quote(r: QuoteReading, lookup: DatasheetLookup) -> Outcome:
    kw = r.heat_pump_kw
    checks = [
        _legible(r, "quote"),
        Check(
            "heat pump size read (2-25 kW)",
            kw is not None and 2 <= kw <= 25,
            f"{kw} kW" if kw is not None else "no kW figure read",
        ),
    ]
    if r.design_flow_temp_c is not None:
        checks.append(
            Check(
                "design flow temperature plausible (25-75 C)",
                25 <= r.design_flow_temp_c <= 75,
                f"{r.design_flow_temp_c} C",
            )
        )
    if r.line_items and r.total_gbp is not None:
        ok, detail = quote_sum_matches(r)
        checks.append(Check("line items add up to the total", ok, detail))
    else:
        checks.append(
            Check("line items add up to the total", False, "no itemised prices", hard=False)
        )
    sheet = match_datasheet(lookup, r.heat_pump_make, r.heat_pump_model, {"heat_pump"})
    checks.append(
        Check(
            "heat pump found in datasheet library",
            sheet is not None,
            f"matched {sheet.make} {sheet.model}" if sheet else "no library entry matches",
            hard=False,
        )
    )
    if sheet and sheet.nominal_capacity_kw and kw is not None:
        nominal = sheet.nominal_capacity_kw
        checks.append(
            Check(
                "quoted kW matches the datasheet",
                abs(nominal - kw) <= max(1.0, 0.15 * nominal),
                f"quoted {kw} kW vs datasheet {nominal} kW",
                hard=False,
            )
        )
    return Outcome(checks, sheet.id if sheet else None)
