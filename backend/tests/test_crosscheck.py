import dataclasses

from gae.heatpump.constants import Glazing, WallType
from gae.heatpump.crosscheck import ReasonCode, Verdict, cross_check
from gae.heatpump.fabric import FabricEstimate, PropertyType, estimate_fabric
from gae.heatpump.measured import MeasuredCaveat, MeasuredEstimate, estimate_measured


def test_reasons_ranked_by_size(sam_fabric: FabricEstimate, sam_measured: MeasuredEstimate) -> None:
    reasons = cross_check(sam_fabric, sam_measured).reasons
    sizes = [r.potential_w_per_k for r in reasons]
    assert sizes == sorted(sizes, reverse=True)
    assert all(r.drivers for r in reasons)
    assert all(0 < r.share_of_gap <= 1 for r in reasons)


def test_ratio_range_brackets_central(
    sam_fabric: FabricEstimate, sam_measured: MeasuredEstimate
) -> None:
    ratio = cross_check(sam_fabric, sam_measured).ratio
    assert ratio.low < ratio.central < ratio.high


def test_agreement_returns_no_reasons(
    sam_fabric: FabricEstimate, sam_measured: MeasuredEstimate
) -> None:
    matched = dataclasses.replace(sam_measured, htc_w_per_k=sam_fabric.htc_w_per_k)
    check = cross_check(sam_fabric, matched)
    assert check.verdict is Verdict.AGREE
    assert check.reasons == ()


def test_measured_higher_points_at_boiler_and_draughts() -> None:
    fabric = estimate_fabric(
        floor_area_m2=90,
        property_type=PropertyType.SEMI_DETACHED,
        year_built=1985,
        wall_type=WallType.CAVITY_FILLED,
        glazing=Glazing.DOUBLE_2003_ONWARDS,
        loft_insulation_mm=270,
    )
    measured = estimate_measured(
        annual_gas_kwh=25_000, heating_degree_days=1_800, monthly_gas_kwh={7: 150}
    )
    check = cross_check(fabric, measured)
    assert check.verdict is Verdict.MEASURED_HIGHER
    codes = {r.code for r in check.reasons}
    assert ReasonCode.BOILER_EFFICIENCY_OVERSTATED in codes
    assert ReasonCode.DRAUGHTIER_THAN_ASSUMED in codes
    assert ReasonCode.INSULATION_OVERSTATED in codes


def test_no_glazing_reason_when_glazing_date_known(sam_measured: MeasuredEstimate) -> None:
    fabric = estimate_fabric(
        floor_area_m2=90,
        property_type=PropertyType.SEMI_DETACHED,
        year_built=1930,
        wall_type=WallType.SOLID_BRICK,
        glazing=Glazing.DOUBLE_2003_ONWARDS,
        loft_insulation_mm=270,
    )
    codes = {r.code for r in cross_check(fabric, sam_measured).reasons}
    assert ReasonCode.DEFAULT_GLAZING_U not in codes
    assert ReasonCode.MISSED_INSULATION in codes  # solid brick could be insulated


def test_flagged_low_reading_weighs_more(
    sam_fabric: FabricEstimate, sam_measured: MeasuredEstimate
) -> None:
    flagged = dataclasses.replace(sam_measured, caveats=(MeasuredCaveat.POSSIBLY_SUNNY,))

    def sunny_size(m: MeasuredEstimate) -> float:
        reasons = cross_check(sam_fabric, m).reasons
        return next(
            r for r in reasons if r.code is ReasonCode.SUNNY_OR_PART_HEATED
        ).potential_w_per_k

    assert sunny_size(flagged) > sunny_size(sam_measured)
