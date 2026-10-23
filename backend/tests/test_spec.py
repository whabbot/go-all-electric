import math

import pytest

from gae.heatpump import constants as c
from gae.heatpump.constants import HeatingFuel
from gae.heatpump.ranges import Confidence, Range
from gae.heatpump.spec import (
    RadiatorStatus,
    Room,
    bus_grant,
    check_radiator,
    min_flow_temp_c,
    radiator_output_w,
    size_range_kw,
    target_spec,
)


def test_radiator_output_at_dt50_is_rated() -> None:
    # Mean water 71C in a 21C room is Delta-T 50.
    assert radiator_output_w(1_000, 71 + 2.5, 21) == pytest.approx(1_000)


def test_radiator_output_uses_n_1_3_exponent() -> None:
    # 45C flow -> 42.5C mean -> Delta-T 21.5: (21.5/50)^1.3 ~= 0.334.
    assert radiator_output_w(1_000, 45, 21) == pytest.approx(1_000 * (21.5 / 50) ** 1.3)
    assert radiator_output_w(1_000, 20, 21) == 0


def test_min_flow_temp_inverts_output() -> None:
    flow = min_flow_temp_c(2_000, 700, 21)
    assert radiator_output_w(2_000, flow, 21) == pytest.approx(700)
    assert min_flow_temp_c(0, 700, 21) == math.inf


def test_radiator_statuses() -> None:
    assert check_radiator(Room("big", 500, 2_500), 45).status is RadiatorStatus.OK
    assert check_radiator(Room("small", 1_200, 1_800), 45).status is RadiatorStatus.UPSIZE
    marginal_rating = 800 / radiator_output_w(1, 45, 21)
    assert check_radiator(Room("edge", 800, marginal_rating), 45).status is RadiatorStatus.MARGINAL


def test_upsize_gives_required_rating() -> None:
    check = check_radiator(Room("living", 1_200, 1_800), 45)
    assert radiator_output_w(check.required_output_dt50_w, 45, 21) == pytest.approx(1_200)


def test_size_range_has_margin() -> None:
    size = size_range_kw(Range(3.7, 4.7, 5.7))
    assert size == Range(5.0, 6.0, 7.0)


def test_target_spec_reports_flow_needed_by_current_radiators() -> None:
    spec = target_spec(
        measured_design_load_kw=Range(3.7, 4.7, 5.7),
        current_fuel=HeatingFuel.GAS,
        rooms=[Room("living", 1_200, 1_800), Room("bed", 400, 1_500)],
    )
    assert spec.max_flow_temp_c.value == c.TARGET_FLOW_TEMP_C
    assert spec.flow_temp_needed_by_current_radiators_c is not None
    assert spec.flow_temp_needed_by_current_radiators_c.value == math.ceil(
        min_flow_temp_c(1_800, 1_200, 21)
    )
    assert [r.status for r in spec.radiators] == [RadiatorStatus.UPSIZE, RadiatorStatus.OK]


def test_target_spec_without_rooms() -> None:
    spec = target_spec(measured_design_load_kw=Range(3, 4, 5), current_fuel=HeatingFuel.OIL)
    assert spec.radiators == ()
    assert spec.flow_temp_needed_by_current_radiators_c is None


def test_target_flow_must_be_in_band() -> None:
    with pytest.raises(ValueError):
        target_spec(
            measured_design_load_kw=Range(3, 4, 5),
            current_fuel=HeatingFuel.GAS,
            target_flow_temp_c=70,
        )


@pytest.mark.parametrize(
    ("fuel", "amount", "confidence"),
    [
        (HeatingFuel.GAS, 7_500, Confidence.HIGH),
        (HeatingFuel.OIL, 9_000, Confidence.HIGH),
        (HeatingFuel.LPG, 9_000, Confidence.HIGH),
        (HeatingFuel.ELECTRIC, 0, Confidence.LOW),
    ],
)
def test_bus_grant_by_fuel(fuel: HeatingFuel, amount: int, confidence: Confidence) -> None:
    grant = bus_grant(fuel)
    assert grant.amount_gbp.value == amount
    assert grant.amount_gbp.confidence is confidence
