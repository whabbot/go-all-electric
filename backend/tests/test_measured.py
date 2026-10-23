import pytest

from gae.heatpump import constants as c
from gae.heatpump.measured import MeasuredCaveat, estimate_measured


def test_formula_matches_hand_calculation() -> None:
    # 10,000 kWh of heating gas at 90% over 2,000 degree days: 9e6 Wh / 48,000 h = 187.5 W/K.
    est = estimate_measured(
        annual_gas_kwh=12_000,
        heating_degree_days=2_000,
        monthly_gas_kwh={6: 2_000 / 12, 7: 2_000 / 12, 8: 2_000 / 12},
        boiler_efficiency=0.9,
    )
    assert est.htc_w_per_k.central == pytest.approx(187.5)
    assert est.design_load_kw.central == pytest.approx(187.5 * 23 / 1000)


def test_range_carries_stated_uncertainty() -> None:
    est = estimate_measured(
        annual_gas_kwh=12_000,
        heating_degree_days=2_000,
        monthly_gas_kwh={7: 150},
        boiler_efficiency=0.9,
    )
    htc = est.htc_w_per_k
    assert htc.low == pytest.approx(htc.central * (1 - c.MEASURED_METHOD_UNCERTAINTY))
    assert htc.high == pytest.approx(htc.central * (1 + c.MEASURED_METHOD_UNCERTAINTY))


def test_annual_only_uses_default_baseline_and_flags_it() -> None:
    est = estimate_measured(annual_gas_kwh=12_000, heating_degree_days=2_000)
    assert MeasuredCaveat.BASELINE_ESTIMATED in est.caveats
    assert MeasuredCaveat.EFFICIENCY_DEFAULTED in est.caveats
    assert est.baseline_gas_kwh.central == pytest.approx(12_000 * c.DEFAULT_BASELINE_FRACTION)
    assert est.boiler_efficiency == c.DEFAULT_BOILER_EFFICIENCY
    # Defaults widen the range beyond the method's own uncertainty.
    assert est.htc_w_per_k.high / est.htc_w_per_k.low > 1.2 / 0.8


def test_monthly_readings_without_summer_fall_back_to_default() -> None:
    est = estimate_measured(
        annual_gas_kwh=12_000, heating_degree_days=2_000, monthly_gas_kwh={1: 2_000, 12: 1_900}
    )
    assert MeasuredCaveat.BASELINE_ESTIMATED in est.caveats


def test_low_specific_heat_loss_flags_sunny_or_part_heated() -> None:
    # 5,000 kWh/yr in a 150 m2 house is too little for typical UK fabric.
    est = estimate_measured(
        annual_gas_kwh=5_000, heating_degree_days=2_000, boiler_efficiency=0.9, floor_area_m2=150
    )
    assert MeasuredCaveat.POSSIBLY_SUNNY in est.caveats
    assert MeasuredCaveat.POSSIBLY_PARTIALLY_HEATED in est.caveats
    htc = est.htc_w_per_k
    # Reads low, so the top of the range is stretched further than the bottom.
    assert htc.high - htc.central > htc.central - htc.low


def test_caller_can_flag_sunny_home() -> None:
    est = estimate_measured(
        annual_gas_kwh=12_000, heating_degree_days=2_000, boiler_efficiency=0.9, sunny=True
    )
    assert MeasuredCaveat.POSSIBLY_SUNNY in est.caveats
    assert MeasuredCaveat.POSSIBLY_PARTIALLY_HEATED not in est.caveats


def test_design_temperature_is_configurable() -> None:
    london = estimate_measured(annual_gas_kwh=12_000, heating_degree_days=2_000)
    colder = estimate_measured(
        annual_gas_kwh=12_000, heating_degree_days=2_000, design_outdoor_temp_c=-5
    )
    assert colder.design_load_kw.central == pytest.approx(london.design_load_kw.central * 26 / 23)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"annual_gas_kwh": 0, "heating_degree_days": 2_000},
        {"annual_gas_kwh": 12_000, "heating_degree_days": 0},
        {"annual_gas_kwh": 12_000, "heating_degree_days": 2_000, "boiler_efficiency": 1.2},
        {"annual_gas_kwh": 1_000, "heating_degree_days": 2_000, "monthly_gas_kwh": {7: 100}},
        {"annual_gas_kwh": 12_000, "heating_degree_days": 2_000, "monthly_gas_kwh": {13: 100}},
    ],
)
def test_rejects_impossible_inputs(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        estimate_measured(**kwargs)
