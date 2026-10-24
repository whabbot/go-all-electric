"""Quote flags in code, and the one-context review with its number check."""

from gae.gemini.client import Call, FakeGemini
from gae.gemini.datasheets import InMemoryDatasheetLookup
from gae.gemini.quotes import SizeContext, flag_quote
from gae.gemini.review import allowed_numbers, review, supported, tidy
from gae.gemini.schemas import (
    ArgonReview,
    ConflictField,
    ConflictStatus,
    EstimateDirection,
    EvidenceSource,
    FuseCutoutReading,
    InputConflictProposal,
    MathsBundle,
    MediaInput,
    OutdoorSpaceReading,
    ProposedValue,
    QuoteInput,
    QuoteReading,
    RadiatorReading,
    RadiatorVideoResult,
    ReviewRequest,
    VerifiedReading,
    VerifiedVideoRadiator,
)
from tests.gemini.conftest import bill, boiler, quote

SAM_SIZE = SizeContext(size_low_kw=5.0, size_high_kw=7.0, design_load_kw=4.7)


def verified(reading: QuoteReading, warnings: list[str] | None = None):
    return VerifiedReading[QuoteReading](
        kind="quote",
        status="verified_with_warnings" if warnings else "verified",
        reading=reading,
        attempts=1,
        warnings=warnings or [],
        photograph_instead=None,
        log=[],
    )


# --- quote flags -----------------------------------------------------------------------------


def test_nine_kw_quote_is_flagged_like_the_demo() -> None:
    result = flag_quote("quote-9kw.pdf", verified(quote()), SAM_SIZE)
    messages = {f.message: f.severity for f in result.flags}
    assert messages["9 kW quoted, your bills suggest about 4.7 kW: oversized"] == "red"
    assert messages["Design flow 55°C: expect higher bills"] == "amber"
    assert messages["Buffer tank: ask why"] == "amber"
    assert messages["Grant not deducted"] == "red"
    assert any("heat loss 8.9 kW" in m for m in messages)
    assert result.quoted_kw == 9.0 and result.design_flow_temp_c == 55
    assert len(result.questions_to_ask) >= 4


def test_right_sized_low_flow_quote_gets_info_only() -> None:
    good = quote(
        heat_pump_model="AirSource 6",
        heat_pump_kw=6.0,
        design_flow_temp_c=40,
        buffer_tank=False,
        grant_deducted=True,
        grant_amount_gbp=7_500,
        mcs_heat_loss_kw=None,
    )
    result = flag_quote("quote-6kw.pdf", verified(good), SAM_SIZE)
    assert {f.severity for f in result.flags} == {"info"}


def test_unreadable_quote_says_so() -> None:
    gave_up = VerifiedReading[QuoteReading](
        kind="quote",
        status="couldnt_tell",
        reading=None,
        attempts=2,
        warnings=["line items add up to the total: no"],
        photograph_instead="the full quote PDF",
        log=[],
    )
    result = flag_quote("blurry.pdf", gave_up, SAM_SIZE)
    assert result.flags[0].message == "Couldn't read this quote reliably"


# --- number check ----------------------------------------------------------------------------


def test_number_matching_respects_written_precision() -> None:
    allowed = [4.716, 1213.4, 0.0, 9.0]
    assert supported("4.7", allowed)
    assert supported("5", allowed)  # "about 5 kW" from 4.716
    assert supported("1,200", allowed)  # rounded to hundreds
    assert supported("1,213", allowed)
    assert not supported("4.9", allowed)
    assert not supported("12", allowed)
    assert not supported("2,000", allowed)


def test_maths_is_rounded_for_the_prompt() -> None:
    assert tidy({"a": 8.746791695661287, "b": [380.29529, 48.324], "c": 0.4676, "d": 7}) == {
        "a": 8.75,
        "b": [380, 48.3],
        "c": 0.47,
        "d": 7,
    }


def test_allowed_numbers_include_percentages_and_kw() -> None:
    allowed = allowed_numbers({"share_of_gap": 0.45, "heat_loss_w": 1500, "note": "R290, 1,200 L"})
    assert {45.0, 1.5, 1500.0, 1200.0} <= set(allowed)
    assert 290.0 not in allowed  # model codes are not numbers


def request(sam_maths: MathsBundle) -> ReviewRequest:
    return ReviewRequest(
        photos=[MediaInput(kind="boiler_plate", data_base64="/9j/AA==", mime_type="image/jpeg")],
        epc_record={"total_floor_area": 90, "construction_age_band": "1930-1949"},
        boiler=boiler(),
        quotes=[
            QuoteInput(
                quote_id="Quote A",
                document=MediaInput(
                    kind="quote", data_base64="JVBERg==", mime_type="application/pdf"
                ),
                reading=quote(),
            )
        ],
        maths=sam_maths,
    )


def argon_reply(sam_maths: MathsBundle) -> ArgonReview:
    load = sam_maths.measured["design_load_kw"]["central"]
    fabric = sam_maths.fabric["design_load_kw"]["central"]
    return ArgonReview(
        estimates_explanation=(
            f"Your bills point to about {load:.1f} kW while the fabric estimate says "
            f"{fabric:.1f} kW. The biggest reason is insulation the EPC missed. "
            "This saves you 3,456 pounds a year."  # invented: must be stripped
        ),
        cited_reason_codes=["missed_insulation", "home_kept_warmer"],
        quote_reviews=[
            {
                "quote_id": "Quote A",
                "flags": [
                    {
                        "severity": "red",
                        "message": "9 kW is above your 5-7 kW range.",
                        "evidence": "MATHS.target_spec.size_kw",
                    },
                    {
                        "severity": "amber",
                        "message": "A 23.45 kW backup heater is listed.",  # invented
                        "evidence": "quote",
                    },
                ],
            },
            {"quote_id": "Quote Z", "flags": []},  # no such quote
        ],
        questions_to_ask=["Why a buffer tank?", "Can you guarantee 7.77 SCOP?"],
        summary="A second opinion: it advises; you decide.",
    )


def test_review_is_one_argon_call_and_strips_unverified_numbers(sam_maths, lookup) -> None:
    gemini = FakeGemini([argon_reply(sam_maths)])
    result = review(gemini, lookup, request(sam_maths))

    (call,) = gemini.calls
    assert isinstance(call, Call)
    assert (call.model, call.thinking_level, call.schema) == (
        "gemini-4-argon",
        "high",
        "ArgonReview",
    )
    assert call.media_types == ["image", "document"]
    # Full datasheets for the matched boiler and quoted heat pump, plus right-sized options.
    assert "FULL DATASHEET synthetic-acme-combi-24i" in call.prompt
    assert "FULL DATASHEET synthetic-zephyr-airsource-9" in call.prompt
    assert "FULL DATASHEET synthetic-zephyr-airsource-6" in call.prompt
    assert '"MATHS"' in call.prompt and "missed_insulation" in call.prompt
    assert "8.746791695661287" not in call.prompt

    cleaned = result.review
    assert "3,456" not in cleaned.estimates_explanation
    assert "insulation the EPC missed" in cleaned.estimates_explanation
    assert [c.value for c in cleaned.cited_reason_codes] == ["missed_insulation"]
    assert [q.quote_id for q in cleaned.quote_reviews] == ["Quote A"]
    (flag,) = cleaned.quote_reviews[0].flags
    assert flag.message == "9 kW is above your 5-7 kW range."
    assert cleaned.questions_to_ask == ["Why a buffer tank?"]
    assert {tuple(s.numbers) for s in result.stripped} == {("3,456",), ("23.45",), ("7.77",)}

    assert result.log[-1].step == "fail"
    assert "removed 3 unverified statement(s)" in result.log[-1].action
    assert any("home_kept_warmer" in e.action for e in result.log)
    assert set(result.datasheets_used) >= {
        "synthetic-acme-combi-24i",
        "synthetic-zephyr-airsource-9",
    }


def test_clean_review_passes(sam_maths, lookup) -> None:
    reply = argon_reply(sam_maths)
    reply.estimates_explanation = "The biggest reason is insulation the EPC missed."
    reply.quote_reviews = []
    reply.questions_to_ask = []
    result = review(FakeGemini([reply]), lookup, request(sam_maths))
    assert result.stripped == []
    assert result.log[-1].step == "pass"


def test_review_never_sends_address_like_epc_fields(sam_maths: MathsBundle) -> None:
    req = request(sam_maths)
    req.epc_record = {
        "address_line_1": "1 Synthetic Street",
        "address_line_2": "Flat B",
        "postcode": "ZZ1 1ZZ",
        "uprn": 100000000001,
        "certificate_number": "0000-1111-2222-3333-4444",
        "lmk_key": "abc123",
        "total_floor_area": 90,
        "walls": [{"description": "Cavity wall", "location_note": "near ZZ1 1ZZ"}],
        "main_heating": [{"description": "Boiler, mains gas", "address": "1 Synthetic Street"}],
    }
    fake = FakeGemini([argon_reply(sam_maths)])
    review(fake, InMemoryDatasheetLookup([]), req)
    prompt = fake.calls[0].prompt
    for private in ("Synthetic Street", "Flat B", "ZZ1", "100000000001", "0000-1111", "abc123"):
        assert private not in prompt
    assert "Cavity wall" in prompt and '"total_floor_area": 90' in prompt


def test_valid_conflict_proposal_reruns_fabric_and_reports_gap_change(
    sam_maths: MathsBundle, lookup: InMemoryDatasheetLookup
) -> None:
    req = request(sam_maths)
    req.outdoor_space = OutdoorSpaceReading(
        legible=True,
        confidence="high",
        notes="Drilled mortar pattern on external wall.",
        clear_width_m=2.0,
        clear_depth_m=1.2,
        surface="paved",
        obstructions=[],
    )
    reply = argon_reply(sam_maths)
    reply.estimates_explanation = "The biggest reason is insulation the EPC missed."
    reply.quote_reviews = []
    reply.questions_to_ask = []
    reply.conflict_status = ConflictStatus.CONFLICTS_FOUND
    reply.input_conflicts = [
        InputConflictProposal(
            field=ConflictField.WALL_TYPE,
            evidence_source=EvidenceSource.OUTDOOR_SPACE,
            evidence_summary="The outdoor wall photo shows retrofit cavity fill drill holes.",
            proposed_value=ProposedValue.CAVITY_FILLED,
            expected_direction=EstimateDirection.LOWER,
        ),
        InputConflictProposal(
            field=ConflictField.WALL_TYPE,
            evidence_source=EvidenceSource.EPC,
            evidence_summary="If the walls were solid brick instead, heat loss would be higher.",
            proposed_value=ProposedValue.SOLID_BRICK,
            expected_direction=EstimateDirection.HIGHER,
        ),
    ]

    orig_fabric_kw = sam_maths.fabric["design_load_kw"]["central"]
    result = review(FakeGemini([reply]), lookup, req)

    assert result.review.conflict_status == ConflictStatus.CONFLICTS_FOUND
    assert len(result.review.input_conflicts) == 2
    assert len(result.tested_conflicts) == 2

    shrinks, grows = result.tested_conflicts
    assert shrinks.field == ConflictField.WALL_TYPE
    assert shrinks.current_value == "cavity_unfilled"
    assert shrinks.proposed_value == ProposedValue.CAVITY_FILLED
    assert shrinks.evidence_source == EvidenceSource.OUTDOOR_SPACE
    assert shrinks.direction_matches is True
    assert shrinks.new_design_load_kw.central < shrinks.original_design_load_kw.central
    assert shrinks.gap_change == "shrinks"
    assert shrinks.new_gap_w_per_k is not None and shrinks.original_gap_w_per_k is not None
    assert shrinks.new_gap_w_per_k < shrinks.original_gap_w_per_k

    assert grows.proposed_value == ProposedValue.SOLID_BRICK
    assert grows.direction_matches is True
    assert grows.new_design_load_kw.central > grows.original_design_load_kw.central
    assert grows.gap_change == "grows"
    assert grows.new_gap_w_per_k is not None and grows.original_gap_w_per_k is not None
    assert grows.new_gap_w_per_k > grows.original_gap_w_per_k

    # Original maths bundle is untouched; code tests alternatives without mutating Estimate A.
    assert sam_maths.fabric["design_load_kw"]["central"] == orig_fabric_kw
    conflict_logs = [e for e in result.log if e.input == "conflicts"]
    assert len(conflict_logs) == 2
    assert all(e.passed for e in conflict_logs)
    assert "gap shrinks" in conflict_logs[0].action
    assert "gap grows" in conflict_logs[1].action


def test_conflict_proposal_citing_unprovided_input_is_rejected(
    sam_maths: MathsBundle, lookup: InMemoryDatasheetLookup
) -> None:
    req = request(sam_maths)
    # radiator_video and fuse_cutout are not provided on `req`.
    reply = argon_reply(sam_maths)
    reply.estimates_explanation = "The biggest reason is insulation the EPC missed."
    reply.quote_reviews = []
    reply.questions_to_ask = []
    reply.conflict_status = ConflictStatus.CONFLICTS_FOUND
    reply.input_conflicts = [
        InputConflictProposal(
            field=ConflictField.GLAZING,
            evidence_source=EvidenceSource.RADIATOR_VIDEO,
            evidence_summary="Modern glazing seen behind the radiators in the video.",
            proposed_value=ProposedValue.DOUBLE_2003_ONWARDS,
            expected_direction=EstimateDirection.LOWER,
        ),
        InputConflictProposal(
            field=ConflictField.LOFT_INSULATION_MM,
            evidence_source=EvidenceSource.FUSE_CUTOUT,
            evidence_summary="Fuse photo shows thick loft insulation.",
            proposed_value=ProposedValue.LOFT_270MM,
            expected_direction=EstimateDirection.LOWER,
        ),
    ]

    result = review(FakeGemini([reply]), lookup, req)
    assert result.tested_conflicts == []
    assert result.review.input_conflicts == []
    assert result.review.conflict_status == ConflictStatus.NO_CONFLICT_FOUND
    conflict_logs = [e for e in result.log if e.input == "conflicts"]
    assert len(conflict_logs) == 2
    assert all(not e.passed for e in conflict_logs)
    assert "radiator_video not provided" in conflict_logs[0].action
    assert "fuse_cutout not provided" in conflict_logs[1].action


def test_conflict_proposal_with_unknown_field_or_invalid_value_is_rejected(
    sam_maths: MathsBundle, lookup: InMemoryDatasheetLookup
) -> None:
    req = request(sam_maths)
    reply = argon_reply(sam_maths)
    reply.estimates_explanation = "The biggest reason is insulation the EPC missed."
    reply.quote_reviews = []
    reply.questions_to_ask = []
    reply.conflict_status = ConflictStatus.CONFLICTS_FOUND
    reply.input_conflicts = [
        InputConflictProposal(
            field="boiler_age_years",
            evidence_source=EvidenceSource.BOILER_PLATE,
            evidence_summary="The boiler data plate shows a recent condensing model.",
            proposed_value=ProposedValue.CAVITY_FILLED,
            expected_direction=EstimateDirection.LOWER,
        ),
        InputConflictProposal(
            field=ConflictField.LOFT_INSULATION_MM,
            evidence_source=EvidenceSource.BOILER_PLATE,
            evidence_summary="Boiler upgrade suggests the loft was topped up too.",
            proposed_value="999mm",
            expected_direction=EstimateDirection.LOWER,
        ),
        InputConflictProposal(
            field=ConflictField.LOFT_INSULATION_MM,
            evidence_source=EvidenceSource.BOILER_PLATE,
            evidence_summary="Mismatched enum value from wall_type.",
            proposed_value=ProposedValue.CAVITY_FILLED,
            expected_direction=EstimateDirection.LOWER,
        ),
    ]

    result = review(FakeGemini([reply]), lookup, req)
    assert result.tested_conflicts == []
    assert result.review.input_conflicts == []
    assert result.review.conflict_status == ConflictStatus.NO_CONFLICT_FOUND
    conflict_logs = [e for e in result.log if e.input == "conflicts"]
    assert len(conflict_logs) == 3
    assert all(not e.passed for e in conflict_logs)
    assert "rejected unknown field" in conflict_logs[0].action
    assert "rejected value outside closed set" in conflict_logs[1].action
    assert "rejected value outside closed set" in conflict_logs[2].action


def test_no_conflict_found_path(sam_maths: MathsBundle, lookup: InMemoryDatasheetLookup) -> None:
    req = request(sam_maths)
    reply = argon_reply(sam_maths)
    reply.estimates_explanation = "The biggest reason is insulation the EPC missed."
    reply.quote_reviews = []
    reply.questions_to_ask = []
    reply.conflict_status = ConflictStatus.NO_CONFLICT_FOUND
    reply.input_conflicts = []

    result = review(FakeGemini([reply]), lookup, req)
    assert result.review.conflict_status == ConflictStatus.NO_CONFLICT_FOUND
    assert result.review.input_conflicts == []
    assert result.tested_conflicts == []
    (conflict_log,) = [e for e in result.log if e.input == "conflicts"]
    assert conflict_log.passed is True
    assert conflict_log.action == "no conflict proposed"


def test_conflict_evidence_summary_is_checked_by_number_guard(
    sam_maths: MathsBundle, lookup: InMemoryDatasheetLookup
) -> None:
    req = request(sam_maths)
    reply = argon_reply(sam_maths)
    reply.estimates_explanation = "The biggest reason is insulation the EPC missed."
    reply.quote_reviews = []
    reply.questions_to_ask = []
    reply.conflict_status = ConflictStatus.CONFLICTS_FOUND
    reply.input_conflicts = [
        InputConflictProposal(
            field=ConflictField.LOFT_INSULATION_MM,
            evidence_source=EvidenceSource.BOILER_PLATE,
            evidence_summary=(
                "The recent boiler plate suggests the home was refurbished after the EPC. "
                "That refurbishment cost 4,321 pounds."
            ),
            proposed_value=ProposedValue.LOFT_270MM,
            expected_direction=EstimateDirection.LOWER,
        )
    ]

    result = review(FakeGemini([reply]), lookup, req)
    assert len(result.tested_conflicts) == 1
    tested = result.tested_conflicts[0]
    assert tested.proposed_value == ProposedValue.LOFT_270MM
    assert "4,321" not in tested.evidence_summary
    assert "refurbished after the EPC" in tested.evidence_summary
    assert [s.numbers for s in result.stripped] == [["4,321"]]
    assert result.log[-1].step == "fail"


def test_review_context_includes_all_verified_readings_and_scrubs_privacy(
    sam_maths: MathsBundle,
) -> None:
    req = request(sam_maths)
    req.bill_reading = bill()
    req.radiators = RadiatorReading(
        legible=True,
        confidence="high",
        notes="Double panel convector in living room.",
        radiator_type="K2",
        height_mm=600,
        width_mm=1200,
        panels=2,
        fin_rows=2,
        room="Living room",
    )
    req.radiator_video = RadiatorVideoResult(
        status="verified",
        attempts=1,
        model="gemini-3.8-flash",
        radiator_count=1,
        radiators=[
            VerifiedVideoRadiator(
                first_seen="0:04",
                last_seen="0:09",
                room="Hallway",
                status="verified",
                radiator_type="K2",
                panels=2,
                fin_rows=2,
                width_mm=1000,
                height_mm=600,
                confidence="high",
            )
        ],
        warnings=["Note with postcode ZZ1 1ZZ and cert 0000-1111-2222-3333-4444"],
        log=[],
    )
    req.fuse_cutout = FuseCutoutReading(
        legible=True,
        confidence="high",
        notes="Main cutout fuse.",
        rating_a=100,
        looks_like="cutout",
    )
    req.outdoor_space = OutdoorSpaceReading(
        legible=True,
        confidence="high",
        notes="Side return.",
        clear_width_m=1.8,
        clear_depth_m=1.1,
        surface="paved",
        obstructions=[],
    )
    req.epc_record = {
        "address_line_1": "1 Synthetic Street",
        "postcode": "ZZ1 1ZZ",
        "uprn": 100000000001,
        "certificate_number": "0000-1111-2222-3333-4444",
        "property_type": "semi_detached",
        "floor_area_m2": 90,
        "storeys": 2,
        "year_built": 1935,
        "wall_type": "cavity_unfilled",
        "glazing": "double_unknown_date",
        "loft_insulation_mm": 100,
        "floor_insulated": False,
    }
    fake = FakeGemini([argon_reply(sam_maths)])
    review(fake, InMemoryDatasheetLookup([]), req)
    prompt = fake.calls[0].prompt
    for section in (
        '"radiators":',
        '"radiator_video":',
        '"fuse_cutout":',
        '"outdoor_space":',
        '"rating_a": 100',
        '"Hallway"',
        '"floor_insulated": false',
    ):
        assert section in prompt
    for private in ("Synthetic Street", "ZZ1", "100000000001", "0000-1111-2222-3333-4444"):
        assert private not in prompt


def test_unreproducible_baseline_is_refused(
    sam_maths: MathsBundle, lookup: InMemoryDatasheetLookup
) -> None:
    req = request(sam_maths)
    # Floor area in epc_record (140 m2) does not match the headline Estimate A (90 m2) within 1%.
    req.epc_record = {"floor_area_m2": 140, "wall_type": "cavity_unfilled"}
    reply = argon_reply(sam_maths)
    reply.estimates_explanation = "The biggest reason is insulation the EPC missed."
    reply.quote_reviews = []
    reply.questions_to_ask = []
    reply.conflict_status = ConflictStatus.CONFLICTS_FOUND
    reply.input_conflicts = [
        InputConflictProposal(
            field=ConflictField.WALL_TYPE,
            evidence_source=EvidenceSource.EPC,
            evidence_summary="EPC assumes unfilled cavity walls.",
            proposed_value=ProposedValue.CAVITY_FILLED,
            expected_direction=EstimateDirection.LOWER,
        )
    ]

    result = review(FakeGemini([reply]), lookup, req)
    assert result.tested_conflicts == []
    assert result.review.input_conflicts == []
    assert result.review.conflict_status == ConflictStatus.NO_CONFLICT_FOUND
    (conflict_log,) = [e for e in result.log if e.input == "conflicts"]
    assert conflict_log.passed is False
    assert "could not reproduce Estimate A" in conflict_log.action
