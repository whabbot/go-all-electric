import pytest

from gae.heatpump import constants as c
from gae.heatpump.constants import Glazing, WallType
from gae.heatpump.fabric import Default, Element, FabricEstimate, PropertyType, estimate_fabric


def _house(**overrides) -> FabricEstimate:
    kwargs = {
        "floor_area_m2": 90,
        "property_type": PropertyType.SEMI_DETACHED,
        "year_built": 1930,
        "wall_type": WallType.CAVITY_UNFILLED,
        "glazing": Glazing.DOUBLE_UNKNOWN_DATE,
        "loft_insulation_mm": 100,
    }
    return estimate_fabric(**(kwargs | overrides))


def test_total_is_sum_of_elements_with_range(sam_fabric: FabricEstimate) -> None:
    total = sum(sam_fabric.element_w_per_k.values())
    assert sam_fabric.htc_w_per_k.central == pytest.approx(total)
    assert sam_fabric.htc_w_per_k.low == pytest.approx(total * (1 - c.FABRIC_METHOD_UNCERTAINTY))


def test_ventilation_uses_installer_default_ach(sam_fabric: FabricEstimate) -> None:
    expected = 0.33 * c.INSTALLER_DEFAULT_ACH_PRE_2000 * 90 * c.ROOM_HEIGHT_M
    assert sam_fabric.element_w_per_k[Element.VENTILATION] == pytest.approx(expected)


def test_defaults_used_are_named(sam_fabric: FabricEstimate) -> None:
    named = {a.default for a in sam_fabric.assumptions}
    assert Default.INSTALLER_AIR_CHANGE_RATE in named
    assert Default.DOUBLE_GLAZING_U_2_8 in named


def test_newer_glazing_does_not_use_2_8_default() -> None:
    est = _house(glazing=Glazing.DOUBLE_2003_ONWARDS)
    assert Default.DOUBLE_GLAZING_U_2_8 not in {a.default for a in est.assumptions}
    assert est.element_w_per_k[Element.WINDOWS] == pytest.approx(est.window_area_m2 * 2.2)


def test_insulation_lowers_heat_loss() -> None:
    base = _house().htc_w_per_k.central
    assert _house(wall_type=WallType.CAVITY_FILLED).htc_w_per_k.central < base
    assert _house(loft_insulation_mm=270).htc_w_per_k.central < base


def test_mid_terrace_loses_less_than_detached() -> None:
    mid = _house(property_type=PropertyType.MID_TERRACE).htc_w_per_k.central
    detached = _house(property_type=PropertyType.DETACHED).htc_w_per_k.central
    assert mid < detached


def test_post_2000_home_uses_lower_ach() -> None:
    est = _house(year_built=2005)
    assert est.air_change_rate == c.INSTALLER_DEFAULT_ACH_2000_ONWARDS
    assert not est.built_before_2000


def test_loft_lookup_takes_entry_at_or_below() -> None:
    assert _house(loft_insulation_mm=120).element_w_per_k[Element.ROOF] == pytest.approx(45 * 0.4)


def test_rejects_bad_floor_area() -> None:
    with pytest.raises(ValueError):
        _house(floor_area_m2=0)
