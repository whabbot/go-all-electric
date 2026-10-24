"""Instant check and the read -> check -> re-read loop, with scripted Gemini replies."""

from gae.gemini.client import FakeGemini
from gae.gemini.extract import extract, glance
from gae.gemini.schemas import FuseCutoutReading, PhotoGlance, PhotoKind, RadiatorReading
from tests.gemini.conftest import JPEG, PDF, bill, boiler, loft, quote


def glance_reply(**overrides) -> PhotoGlance:
    values = dict(
        detected_kind="boiler_plate",
        legible=True,
        key_fields=[
            {"name": "make", "value": "Acme Heating"},
            {"name": "output_kw", "value": "24"},
        ],
        confidence="high",
        summary="legible, 24 kW Acme",
        retake_hint=None,
        face_visible=False,
        number_plate_visible=False,
        house_or_street_visible=False,
        mail_or_envelope_visible=False,
        name_address_or_meter_visible=False,
    )
    return PhotoGlance(**{**values, **overrides})


# --- instant check ---------------------------------------------------------------------------


def test_legible_photo_is_usable_with_key_fields() -> None:
    gemini = FakeGemini([glance_reply()])
    result = glance(gemini, PhotoKind.BOILER_PLATE, JPEG, "image/jpeg")
    assert result.usable and result.legible and result.matches_expected
    assert result.key_fields == {"make": "Acme Heating", "output_kw": "24"}
    assert result.retake_hint is None and result.privacy_warning is None
    (call,) = gemini.calls
    assert (call.model, call.thinking_level) == ("gemini-3.8-flash", "low")
    assert call.media_types == ["image"]


def test_blurry_photo_gets_a_retake_hint() -> None:
    gemini = FakeGemini(
        [
            glance_reply(
                legible=False,
                key_fields=[],
                summary="too blurry",
                retake_hint="too blurry, move closer",
            )
        ]
    )
    result = glance(gemini, PhotoKind.BOILER_PLATE, JPEG, "image/jpeg")
    assert not result.usable
    assert result.retake_hint == "too blurry, move closer"


def test_wrong_subject_falls_back_to_our_hint() -> None:
    gemini = FakeGemini([glance_reply(detected_kind="gas_meter", key_fields=[], retake_hint=None)])
    result = glance(gemini, PhotoKind.FUSE_CUTOUT, JPEG, "image/jpeg")
    assert result.kind == "gas_meter" and not result.matches_expected and not result.usable
    assert "not the meter" in result.retake_hint


def test_face_or_number_plate_is_flagged() -> None:
    gemini = FakeGemini([glance_reply(detected_kind="outdoor_space", number_plate_visible=True)])
    result = glance(gemini, PhotoKind.OUTDOOR_SPACE, JPEG, "image/jpeg")
    assert "number plate" in result.privacy_warning


# --- verification loop -----------------------------------------------------------------------


def test_clean_read_verifies_first_time_on_flash(lookup) -> None:
    gemini = FakeGemini([boiler()])
    result = extract(gemini, lookup, PhotoKind.BOILER_PLATE, JPEG, "image/jpeg")
    assert result.status == "verified" and result.attempts == 1
    assert result.datasheet_id == "synthetic-acme-combi-24i"
    assert [c.model for c in gemini.calls] == ["gemini-3.8-flash"]
    steps = [e.step for e in result.log]
    assert steps[0] == "read" and steps[-1] == "pass" and "check" in steps
    assert all(e.passed for e in result.log)


def test_failed_check_rereads_on_argon_and_recovers(lookup) -> None:
    # First read misreads the output as 32 kW; the catalogue says 4-24 kW for this model.
    gemini = FakeGemini([boiler(heating_output_kw=32.0), boiler(heating_output_kw=20.0)])
    result = extract(gemini, lookup, PhotoKind.BOILER_PLATE, JPEG, "image/jpeg")
    assert result.status == "verified" and result.attempts == 2
    assert result.reading.heating_output_kw == 20.0
    _, second = gemini.calls
    assert (second.model, second.thinking_level) == ("gemini-4-argon", "high")
    assert "plate output within catalogue range" in second.prompt
    assert "32.0" in second.prompt  # the previous reading is shown back
    assert second.media_types == ["image"]  # the image is sent again (store=False)
    failed = [e for e in result.log if not e.passed]
    assert failed[0].action == "ask Gemini to look again"
    assert [e.step for e in result.log].count("reread") == 1


def test_gives_up_with_what_to_photograph(lookup) -> None:
    unreadable = boiler(legible=False, make=None, model=None, heating_output_kw=None)
    gemini = FakeGemini([unreadable, unreadable])
    result = extract(gemini, lookup, PhotoKind.BOILER_PLATE, JPEG, "image/jpeg")
    assert result.status == "couldnt_tell"
    assert result.reading is None  # never show a guess
    assert "data plate" in result.photograph_instead
    assert result.log[-1].step == "fail"
    assert "couldn't tell" in result.log[-1].action
    assert len(gemini.calls) == 2


def test_unknown_model_is_a_soft_warning(lookup) -> None:
    other = boiler(make="Othermake", model="Model X")
    gemini = FakeGemini([other, other])
    result = extract(gemini, lookup, PhotoKind.BOILER_PLATE, JPEG, "image/jpeg")
    assert result.status == "verified_with_warnings"
    assert result.reading is not None and result.datasheet_id is None
    assert any("datasheet library" in w for w in result.warnings)


def test_partial_year_bill_is_flagged_not_rejected(lookup) -> None:
    quarter = bill(period_start="2026-01-01", period_end="2026-03-31", total_kwh=5_000)
    gemini = FakeGemini([quarter, quarter])
    result = extract(gemini, lookup, PhotoKind.GAS_BILL, JPEG, "image/jpeg")
    assert result.status == "verified_with_warnings"
    assert any("partial year" in w for w in result.warnings)
    assert gemini.calls[0].model == "gemini-4-argon"  # bills start on the lead model


def test_bill_months_must_add_up(lookup) -> None:
    months = [{"month": f"2025-{m:02d}", "kwh": 500} for m in range(10, 13)] + [
        {"month": f"2026-{m:02d}", "kwh": 500} for m in range(1, 10)
    ]
    wrong = bill(monthly=months, total_kwh=12_000)  # months sum to 6,000
    right = bill(monthly=[{**m, "kwh": 1_000} for m in months], total_kwh=12_000)
    gemini = FakeGemini([wrong, right])
    result = extract(gemini, lookup, PhotoKind.GAS_BILL, JPEG, "image/jpeg")
    assert result.status == "verified" and result.attempts == 2
    assert "monthly figures add up" in gemini.calls[1].prompt
    assert result.reading.kwh_by_calendar_month()[1] == 1_000


def test_implausible_kwh_cannot_be_used(lookup) -> None:
    misread = bill(total_kwh=120_000)  # likely a meter reading, not kWh used
    gemini = FakeGemini([misread, misread])
    result = extract(gemini, lookup, PhotoKind.GAS_BILL, JPEG, "image/jpeg")
    assert result.status == "couldnt_tell"
    assert "annual gas statement" in result.photograph_instead


def test_meter_instead_of_cutout(lookup) -> None:
    meter = FuseCutoutReading(
        legible=True, confidence="high", notes="", rating_a=None, looks_like="meter"
    )
    gemini = FakeGemini([meter, meter])
    result = extract(gemini, lookup, PhotoKind.FUSE_CUTOUT, JPEG, "image/jpeg")
    assert result.status == "couldnt_tell"
    assert "not the meter" in result.photograph_instead
    assert any("looks like the meter" in e.check for e in result.log)


def test_radiator_type_mismatch_is_a_warning(lookup) -> None:
    rad = RadiatorReading(
        legible=True,
        confidence="medium",
        notes="",
        radiator_type="K2",
        height_mm=600,
        width_mm=1000,
        panels=2,
        fin_rows=1,
        room="lounge",
    )
    result = extract(FakeGemini([rad, rad]), lookup, PhotoKind.RADIATORS, JPEG, "image/jpeg")
    assert result.status == "verified_with_warnings"


def test_quote_sum_mismatch_rereads_then_gives_up(lookup) -> None:
    bad = quote(total_gbp=15_000)  # items sum to 13,500
    gemini = FakeGemini([bad, bad])
    result = extract(gemini, lookup, "quote", PDF, "application/pdf")
    assert result.status == "couldnt_tell"
    assert gemini.calls[0].media_types == ["document"]
    assert "line items add up to the total" in gemini.calls[1].prompt
    assert any("£13,500.00 vs total £15,000.00" in e.check for e in result.log)


def test_quote_grant_below_the_line_adds_up(lookup) -> None:
    after_grant = quote(total_gbp=6_000, grant_deducted=True, grant_amount_gbp=7_500)
    result = extract(FakeGemini([after_grant]), lookup, "quote", PDF, "application/pdf")
    assert result.status == "verified"
    assert result.datasheet_id == "synthetic-zephyr-airsource-9"


def test_quoted_kw_against_datasheet(lookup) -> None:
    mismatch = quote(heat_pump_kw=12.0)  # AirSource 9 is a 9 kW unit
    gemini = FakeGemini([mismatch, mismatch])
    result = extract(gemini, lookup, "quote", PDF, "application/pdf")
    assert result.status == "verified_with_warnings"
    assert any(w.startswith("quoted kW matches the datasheet") for w in result.warnings)


def test_loft_photo_verifies_on_flash_and_glance(lookup) -> None:
    glance_gemini = FakeGemini(
        [
            glance_reply(
                detected_kind="loft",
                key_fields=[
                    {"name": "insulation_visible", "value": "true"},
                    {"name": "depth_mm_band", "value": "270mm"},
                ],
                summary="deep loft wool over joists",
            )
        ]
    )
    glance_res = glance(glance_gemini, PhotoKind.LOFT, JPEG, "image/jpeg")
    assert glance_res.usable and glance_res.matches_expected
    assert glance_res.key_fields["depth_mm_band"] == "270mm"

    gemini = FakeGemini([loft()])
    result = extract(gemini, lookup, PhotoKind.LOFT, JPEG, "image/jpeg")
    assert result.status == "verified" and result.attempts == 1
    assert result.reading.depth_mm_band == "270mm"
    assert result.reading.insulation_visible is True
    assert [c.model for c in gemini.calls] == ["gemini-3.8-flash"]


def test_loft_without_visible_insulation_is_couldnt_tell(lookup) -> None:
    dark = loft(insulation_visible=False, depth_mm_band=None)
    gemini = FakeGemini([dark, dark])
    result = extract(gemini, lookup, PhotoKind.LOFT, JPEG, "image/jpeg")
    assert result.status == "couldnt_tell"
    assert result.reading is None
    assert "loft floor from the hatch" in result.photograph_instead
    assert len(gemini.calls) == 2
    assert (gemini.calls[1].model, gemini.calls[1].thinking_level) == ("gemini-4-argon", "high")


def test_loft_missing_depth_rereads_on_argon_and_recovers(lookup) -> None:
    first = loft(depth_mm_band=None)
    second = loft(depth_mm_band="200mm", joists_visible_above_insulation=False)
    gemini = FakeGemini([first, second])
    result = extract(gemini, lookup, PhotoKind.LOFT, JPEG, "image/jpeg")
    assert result.status == "verified" and result.attempts == 2
    assert result.reading.depth_mm_band == "200mm"
    assert "depth band in allowed set" in gemini.calls[1].prompt


def test_loft_joists_visible_at_270mm_is_a_soft_warning(lookup) -> None:
    inconsistent = loft(depth_mm_band="270mm", joists_visible_above_insulation=True)
    gemini = FakeGemini([inconsistent, inconsistent])
    result = extract(gemini, lookup, PhotoKind.LOFT, JPEG, "image/jpeg")
    assert result.status == "verified_with_warnings"
    assert result.reading is not None
    assert any("joist visibility consistent with depth band" in w for w in result.warnings)
