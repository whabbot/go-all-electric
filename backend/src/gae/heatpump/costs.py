"""Cost answer: annual gas cost vs heat pump running cost at today's price cap.

Heat pump efficiency falls ~3% for each degree of design flow temperature, so the answer is a
range across installation quality and depends on how hot the radiators have to run. Standing
charges are excluded.
"""

import math
from dataclasses import dataclass

from gae.heatpump import constants as c
from gae.heatpump.ranges import Confidence, Exact, Range


@dataclass(frozen=True)
class Prices:
    electricity_pence_per_kwh: float = c.ELECTRICITY_PENCE_PER_KWH
    gas_pence_per_kwh: float = c.GAS_PENCE_PER_KWH
    period: str = c.PRICE_CAP_PERIOD


@dataclass(frozen=True)
class CostComparison:
    design_flow_temp_c: float
    space_heat_kwh: float
    hot_water_heat_kwh: float
    space_heating_scop: Range
    # The current gas bill is known from the bills themselves, so it is exact.
    gas_cost_gbp: Exact
    heat_pump_cost_gbp: Range
    # Positive means the heat pump is cheaper. low/high follow the SCOP range.
    annual_saving_gbp: Range
    # Space-heating SCOP at which the heat pump costs the same as gas.
    break_even_scop: Exact
    # Design flow temperature above which the heat pump costs more: low for a poor install,
    # high for a good one. Not clipped to the 35-55C design band, so a value below 35C means
    # the heat pump costs more at any practical flow temperature.
    break_even_flow_temp_c: Range
    prices: Prices


def scop_at_flow_temp(flow_temp_c: float) -> Range:
    """Space-heating seasonal COP at a design flow temperature, with installation spread."""
    central = c.REFERENCE_SCOP * (1 - c.SCOP_LOSS_PER_DEGREE) ** (
        flow_temp_c - c.REFERENCE_FLOW_TEMP_C
    )
    central = min(c.SCOP_MAX, max(c.SCOP_MIN, central))
    return Range(
        max(c.SCOP_MIN, central - c.SCOP_SPREAD),
        central,
        min(c.SCOP_MAX, central + c.SCOP_SPREAD),
    )


def flow_temp_for_scop(scop: float) -> float:
    """Inverse of the central SCOP curve: the flow temperature that gives this SCOP."""
    if scop <= 0:
        raise ValueError("scop must be positive")
    return c.REFERENCE_FLOW_TEMP_C + math.log(scop / c.REFERENCE_SCOP) / math.log(
        1 - c.SCOP_LOSS_PER_DEGREE
    )


def compare_running_costs(
    *,
    annual_gas_kwh: float,
    heating_gas_kwh: float,
    boiler_efficiency: float,
    design_flow_temp_c: float,
    prices: Prices | None = None,
) -> CostComparison:
    """Compare a year on gas with a year on a heat pump delivering the same heat.

    `heating_gas_kwh` is the space-heating share of `annual_gas_kwh` (for example the central
    value from the measured estimate); the rest is treated as hot water, which the heat pump
    also supplies at a lower COP. Cooking on gas is a small share and is not separated out.
    """
    prices = prices or Prices()
    if annual_gas_kwh <= 0:
        raise ValueError("annual_gas_kwh must be positive")
    if not 0 < heating_gas_kwh <= annual_gas_kwh:
        raise ValueError("heating_gas_kwh must be positive and at most annual_gas_kwh")
    if not 0.5 <= boiler_efficiency <= 1.0:
        raise ValueError("boiler_efficiency must be between 0.5 and 1.0")

    space_heat = heating_gas_kwh * boiler_efficiency
    hot_water_heat = (annual_gas_kwh - heating_gas_kwh) * boiler_efficiency
    elec = prices.electricity_pence_per_kwh / 100
    gas = prices.gas_pence_per_kwh / 100

    gas_cost = annual_gas_kwh * gas
    hot_water_cost = hot_water_heat / c.HOT_WATER_SCOP * elec

    def hp_cost(scop: float) -> float:
        return space_heat / scop * elec + hot_water_cost

    scop = scop_at_flow_temp(design_flow_temp_c)
    # Lower SCOP costs more, so the bounds swap.
    hp = Range(hp_cost(scop.high), hp_cost(scop.central), hp_cost(scop.low))
    saving = Range(gas_cost - hp.high, gas_cost - hp.central, gas_cost - hp.low)

    budget_for_space = gas_cost - hot_water_cost
    if budget_for_space <= 0:
        raise ValueError("hot water alone would cost more than the current gas bill")
    break_even = space_heat * elec / budget_for_space

    return CostComparison(
        design_flow_temp_c=design_flow_temp_c,
        space_heat_kwh=space_heat,
        hot_water_heat_kwh=hot_water_heat,
        space_heating_scop=scop,
        gas_cost_gbp=Exact(gas_cost, Confidence.HIGH),
        heat_pump_cost_gbp=hp,
        annual_saving_gbp=saving,
        break_even_scop=Exact(break_even, Confidence.MEDIUM),
        break_even_flow_temp_c=Range(
            # A poor install's curve sits SCOP_SPREAD below central, so it reaches break-even
            # where the central curve is SCOP_SPREAD above it.
            flow_temp_for_scop(break_even + c.SCOP_SPREAD),
            flow_temp_for_scop(break_even),
            flow_temp_for_scop(max(break_even - c.SCOP_SPREAD, c.SCOP_MIN)),
        ),
        prices=prices,
    )
