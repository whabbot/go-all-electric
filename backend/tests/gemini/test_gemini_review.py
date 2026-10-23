"""Quote flags in code, and the one-context review with its number check."""

from gae.gemini.client import Call, FakeGemini
from gae.gemini.datasheets import InMemoryDatasheetLookup
from gae.gemini.quotes import SizeContext, flag_quote
from gae.gemini.review import allowed_numbers, review, supported, tidy
from gae.gemini.schemas import (
    ArgonReview,
    MathsBundle,
    MediaInput,
    QuoteInput,
    QuoteReading,
    ReviewRequest,
    VerifiedReading,
)
from tests.gemini.conftest import boiler, quote

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
