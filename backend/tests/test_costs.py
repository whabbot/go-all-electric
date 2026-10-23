import pytest

from gae.heatpump import constants as c
from gae.heatpump.costs import (
    Prices,
    compare_running_costs,
    flow_temp_for_scop,
    scop_at_flow_temp,
)


def test_scop_falls_about_3_percent_per_degree() -> None:
    at_40 = scop_at_flow_temp(40).central
    at_41 = scop_at_flow_temp(41).central
    assert at_41 / at_40 == pytest.approx(1 - c.SCOP_LOSS_PER_DEGREE)
    assert scop_at_flow_temp(40).central == c.REFERENCE_SCOP


def test_scop_range_spread_and_bounds() -> None:
    scop = scop_at_flow_temp(45)
    assert scop.high - scop.central == pytest.approx(c.SCOP_SPREAD)
    assert scop_at_flow_temp(-50).high <= c.SCOP_MAX
    assert scop_at_flow_temp(120).low >= c.SCOP_MIN


def test_flow_temp_for_scop_inverts_curve() -> None:
    assert flow_temp_for_scop(scop_at_flow_temp(47).central) == pytest.approx(47)


def _compare(flow: float, **kwargs):
    args = {
        "annual_gas_kwh": 12_000,
        "heating_gas_kwh": 10_000,
        "boiler_efficiency": 0.88,
        "design_flow_temp_c": flow,
    }
    return compare_running_costs(**(args | kwargs))


def test_gas_cost_uses_price_cap() -> None:
    result = _compare(45)
    assert result.gas_cost_gbp.value == pytest.approx(12_000 * c.GAS_PENCE_PER_KWH / 100)


def test_break_even_scop_is_where_costs_match() -> None:
    result = _compare(45)
    scop = result.break_even_scop.value
    elec = c.ELECTRICITY_PENCE_PER_KWH / 100
    hp = result.space_heat_kwh / scop * elec + result.hot_water_heat_kwh / c.HOT_WATER_SCOP * elec
    assert hp == pytest.approx(result.gas_cost_gbp.value)
    # With no hot water the break-even is efficiency x price ratio.
    no_dhw = _compare(45, heating_gas_kwh=12_000).break_even_scop.value
    assert no_dhw == pytest.approx(0.88 * c.ELECTRICITY_PENCE_PER_KWH / c.GAS_PENCE_PER_KWH)


def test_project_plan_rule_of_thumb_holds() -> None:
    # "SCOP 3.5 beats gas; a poorly set-up 2.5 costs more."
    be = _compare(45).break_even_scop.value
    assert 2.5 < be < 3.5


def test_break_even_flow_temp_orders_by_install_quality() -> None:
    result = _compare(45)
    flow = result.break_even_flow_temp_c
    assert flow.low < flow.central < flow.high
    assert scop_at_flow_temp(flow.central).central == pytest.approx(result.break_even_scop.value)
    # Below break-even flow the heat pump saves money; above it costs more.
    assert _compare(flow.central - 2).annual_saving_gbp.central > 0
    assert _compare(flow.central + 2).annual_saving_gbp.central < 0


def test_saving_range_brackets_central() -> None:
    saving = _compare(45).annual_saving_gbp
    assert saving.low < saving.central < saving.high


def test_prices_are_overridable() -> None:
    cheap = _compare(45, prices=Prices(electricity_pence_per_kwh=15.0))
    assert cheap.annual_saving_gbp.central > _compare(45).annual_saving_gbp.central


def test_rejects_heating_above_annual() -> None:
    with pytest.raises(ValueError):
        _compare(45, heating_gas_kwh=13_000)
