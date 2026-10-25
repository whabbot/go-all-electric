"""Estimate B: heat loss measured from gas bills and heating degree days.

HTC (W/K) = E_gas,heating (kWh) x boiler_efficiency x 1000 / (DD x 24)
P_design (W) = HTC x (T_in - T_design)

The bills have already measured the house; the main error sources are the hot-water and cooking
baseline, the boiler efficiency, and homes that read low because they are sunny or only partly
heated. Those are reported as caveat flags rather than hidden.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from gae.heatpump import constants as c
from gae.heatpump.ranges import Range


class MeasuredCaveat(StrEnum):
    # No summer months available: the hot-water/cooking share is a default fraction.
    BASELINE_ESTIMATED = "baseline_estimated"
    PARTIAL_COVERAGE = "partial_coverage"
    # Boiler efficiency was not read from the data plate.
    EFFICIENCY_DEFAULTED = "efficiency_defaulted"
    # Solar gain lowers gas use, so the bills under-read heat loss.
    POSSIBLY_SUNNY = "possibly_sunny"
    # Rooms left unheated lower gas use, so the bills under-read heat loss.
    POSSIBLY_PARTIALLY_HEATED = "possibly_partially_heated"


@dataclass(frozen=True)
class MeasuredEstimate:
    heating_gas_kwh: Range
    baseline_gas_kwh: Range
    boiler_efficiency: float
    htc_w_per_k: Range
    design_load_kw: Range
    indoor_temp_c: float
    design_outdoor_temp_c: float
    caveats: tuple[MeasuredCaveat, ...]


def estimate_measured(
    *,
    annual_gas_kwh: float,
    heating_degree_days: float,
    monthly_gas_kwh: Mapping[int, float] | None = None,
    boiler_efficiency: float | None = None,
    baseline_gas_kwh: Range | None = None,
    extra_uncertainty: float = 0,
    indoor_temp_c: float = c.DESIGN_INDOOR_TEMP_C,
    design_outdoor_temp_c: float = c.LONDON_DESIGN_OUTDOOR_TEMP_C,
    floor_area_m2: float | None = None,
    sunny: bool = False,
    partially_heated: bool = False,
) -> MeasuredEstimate:
    """Estimate heat transfer coefficient and design heat load from a year of gas use.

    `monthly_gas_kwh` maps month number (1-12) to kWh; any summer months present (June-August)
    set the hot-water/cooking baseline. Without them a default baseline fraction is used and
    flagged. `floor_area_m2`, when known, lets an implausibly low specific heat loss raise the
    sunny/part-heated flags; `sunny` and `partially_heated` let the caller raise them directly.
    """
    if annual_gas_kwh <= 0:
        raise ValueError("annual_gas_kwh must be positive")
    if heating_degree_days <= 0:
        raise ValueError("heating_degree_days must be positive")
    if indoor_temp_c <= design_outdoor_temp_c:
        raise ValueError("indoor_temp_c must be above design_outdoor_temp_c")

    caveats: list[MeasuredCaveat] = []

    efficiency_defaulted = boiler_efficiency is None
    efficiency = c.DEFAULT_BOILER_EFFICIENCY if boiler_efficiency is None else boiler_efficiency
    if not 0.5 <= efficiency <= 1.0:
        raise ValueError("boiler_efficiency must be between 0.5 and 1.0")
    if efficiency_defaulted:
        caveats.append(MeasuredCaveat.EFFICIENCY_DEFAULTED)

    baseline = baseline_gas_kwh or _baseline_gas_kwh(annual_gas_kwh, monthly_gas_kwh)
    if baseline is None:
        caveats.append(MeasuredCaveat.BASELINE_ESTIMATED)
        baseline = Range(
            annual_gas_kwh * c.DEFAULT_BASELINE_FRACTION_LOW,
            annual_gas_kwh * c.DEFAULT_BASELINE_FRACTION,
            annual_gas_kwh * c.DEFAULT_BASELINE_FRACTION_HIGH,
        )
    if baseline.high >= annual_gas_kwh:
        raise ValueError("summer baseline accounts for all gas use; no space heating to measure")

    # A higher baseline leaves less gas for heating, so the bounds swap.
    heating_gas = Range(
        annual_gas_kwh - baseline.high,
        annual_gas_kwh - baseline.central,
        annual_gas_kwh - baseline.low,
    )

    def htc(heating_kwh: float) -> float:
        return heating_kwh * efficiency * 1000 / (heating_degree_days * 24)

    central_htc = htc(heating_gas.central)

    if floor_area_m2 is not None:
        if floor_area_m2 <= 0:
            raise ValueError("floor_area_m2 must be positive")
        if central_htc / floor_area_m2 < c.LOW_SPECIFIC_HTC_W_PER_K_M2:
            sunny = True
            partially_heated = True
    if sunny:
        caveats.append(MeasuredCaveat.POSSIBLY_SUNNY)
    if partially_heated:
        caveats.append(MeasuredCaveat.POSSIBLY_PARTIALLY_HEATED)

    uncertainty = min(0.9, c.MEASURED_METHOD_UNCERTAINTY + extra_uncertainty)
    if efficiency_defaulted:
        uncertainty += c.DEFAULTED_EFFICIENCY_UNCERTAINTY
    upside = uncertainty + (c.LOW_READING_UPLIFT if sunny or partially_heated else 0.0)

    htc_range = Range(
        htc(heating_gas.low) * (1 - uncertainty),
        central_htc,
        htc(heating_gas.high) * (1 + upside),
    )
    delta_t = indoor_temp_c - design_outdoor_temp_c

    return MeasuredEstimate(
        heating_gas_kwh=heating_gas,
        baseline_gas_kwh=baseline,
        boiler_efficiency=efficiency,
        htc_w_per_k=htc_range,
        design_load_kw=htc_range.scale(delta_t / 1000),
        indoor_temp_c=indoor_temp_c,
        design_outdoor_temp_c=design_outdoor_temp_c,
        caveats=tuple(caveats),
    )


def _baseline_gas_kwh(
    annual_gas_kwh: float, monthly_gas_kwh: Mapping[int, float] | None
) -> Range | None:
    """Annual non-heating gas use from the summer months present, or None if there are none."""
    if not monthly_gas_kwh:
        return None
    for month, kwh in monthly_gas_kwh.items():
        if not 1 <= month <= 12:
            raise ValueError(f"month must be 1-12, got {month}")
        if kwh < 0:
            raise ValueError("monthly gas use cannot be negative")
    summer = [monthly_gas_kwh[m] for m in c.SUMMER_MONTHS if m in monthly_gas_kwh]
    if not summer:
        return None
    # The lowest summer month is the purest baseline (no stray heating); the mean is central.
    return Range(min(summer) * 12, sum(summer) / len(summer) * 12, max(summer) * 12)
