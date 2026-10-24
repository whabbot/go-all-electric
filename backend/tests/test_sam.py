"""Worked example: Sam's 1930s semi and three quotes (6kW, 9kW, 12kW)."""

import pytest

from gae.heatpump.constants import HeatingFuel
from gae.heatpump.costs import compare_running_costs
from gae.heatpump.crosscheck import ReasonCode, Verdict, cross_check
from gae.heatpump.fabric import FabricEstimate
from gae.heatpump.measured import MeasuredEstimate
from gae.heatpump.spec import target_spec
from tests.conftest import SAM_ANNUAL_GAS_KWH, SAM_BOILER_EFFICIENCY


def test_sam_bills_say_about_5kw(sam_measured: MeasuredEstimate) -> None:
    assert SAM_ANNUAL_GAS_KWH == 12_000
    load = sam_measured.design_load_kw
    assert load.central == pytest.approx(4.7, abs=0.1)
    assert load.contains(5.0)
    assert sam_measured.caveats == ()


def test_sam_fabric_calc_says_about_9kw(sam_fabric: FabricEstimate) -> None:
    load = sam_fabric.design_load_kw
    assert load.central == pytest.approx(8.7, abs=0.2)
    assert load.contains(9.0)


def test_sam_mismatch_is_explained(
    sam_fabric: FabricEstimate, sam_measured: MeasuredEstimate
) -> None:
    check = cross_check(sam_fabric, sam_measured)
    assert check.verdict is Verdict.FABRIC_HIGHER
    assert check.ratio.central == pytest.approx(1.85, abs=0.05)
    codes = [r.code for r in check.reasons]
    assert set(codes) == {
        ReasonCode.MISSED_INSULATION,
        ReasonCode.DEFAULT_AIR_CHANGE_RATE,
        ReasonCode.SUNNY_OR_PART_HEATED,
        ReasonCode.DEFAULT_GLAZING_U,
    }
    # Between them the named defaults can explain most of the gap.
    assert sum(r.share_of_gap for r in check.reasons) > 0.9


def test_sam_target_spec_flags_9_and_12kw_quotes_as_oversized(
    sam_measured: MeasuredEstimate,
) -> None:
    spec = target_spec(
        measured_design_load_kw=sam_measured.design_load_kw, current_fuel=HeatingFuel.GAS
    )
    assert (spec.size_kw.low, spec.size_kw.high) == (5.0, 7.0)
    assert spec.size_kw.contains(6.0)
    assert not spec.size_kw.contains(9.0)
    assert not spec.size_kw.contains(12.0)
    assert spec.grant.amount_gbp.value == 7_500


def test_sam_cost_depends_on_flow_temperature(sam_measured: MeasuredEstimate) -> None:
    def saving(flow: float) -> float:
        return compare_running_costs(
            annual_gas_kwh=SAM_ANNUAL_GAS_KWH,
            heating_gas_kwh=sam_measured.heating_gas_kwh.central,
            boiler_efficiency=SAM_BOILER_EFFICIENCY,
            design_flow_temp_c=flow,
        ).annual_saving_gbp.central

    assert saving(40) > 0
    assert saving(55) < 0


def test_sam_argon_conflict_proposal_is_tested_by_code(
    sam_fabric: FabricEstimate, sam_measured: MeasuredEstimate
) -> None:
    from gae.gemini.client import FakeGemini
    from gae.gemini.datasheets import InMemoryDatasheetLookup
    from gae.gemini.review import review
    from gae.gemini.schemas import (
        ArgonReview,
        ConflictField,
        ConflictStatus,
        EstimateDirection,
        EvidenceSource,
        InputConflictProposal,
        MathsBundle,
        ProposedValue,
        ReviewRequest,
    )

    bundle = MathsBundle.from_core(
        sam_measured,
        sam_fabric,
        cross_check(sam_fabric, sam_measured),
        [],
        target_spec(
            measured_design_load_kw=sam_measured.design_load_kw, current_fuel=HeatingFuel.GAS
        ),
    )
    reply = ArgonReview(
        estimates_explanation="Your bills read lower than the EPC fabric estimate.",
        cited_reason_codes=[ReasonCode.MISSED_INSULATION],
        conflict_status=ConflictStatus.CONFLICTS_FOUND,
        input_conflicts=[
            InputConflictProposal(
                field=ConflictField.WALL_TYPE,
                evidence_source=EvidenceSource.EPC,
                evidence_summary=(
                    "EPC assumes unfilled cavity walls; filled cavities explain the lower bills."
                ),
                proposed_value=ProposedValue.CAVITY_FILLED,
                expected_direction=EstimateDirection.LOWER,
            )
        ],
        quote_reviews=[],
        questions_to_ask=[],
        summary="Your bills point to filled cavities.",
    )
    req = ReviewRequest(
        epc_record={"wall_type": "cavity_unfilled", "total_floor_area": 95},
        maths=bundle,
    )
    result = review(FakeGemini([reply]), InMemoryDatasheetLookup([]), req)
    (tested,) = result.tested_conflicts
    assert tested.field == ConflictField.WALL_TYPE
    assert tested.proposed_value == ProposedValue.CAVITY_FILLED
    assert tested.gap_change == "shrinks"
    assert tested.new_design_load_kw.central < sam_fabric.design_load_kw.central
