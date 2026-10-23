"""Installer drafts: Argon writes, code checks every number, the template catches the rest.

No network: Gemini is `FakeGemini` and the datasheet library is the public seed in memory.
"""

import json

import pytest
from fastapi.testclient import TestClient

from gae.db.seed import load_seed
from gae.gemini.client import Call, FakeGemini, GeminiError
from gae.gemini.datasheets import InMemoryDatasheetLookup
from gae.gemini.router import get_datasheets, get_gemini
from gae.main import app
from gae.pack.drafts import draft_installer_emails, right_sized_models, template
from gae.pack.schemas import ArgonEmail, InstallerDraftsRequest

SEED = InMemoryDatasheetLookup(load_seed())
SEED_IDS = {s.id: s for s in SEED.sheets}

# Sam's numbers: bills say about 4.7 kW, target a 5-7 kW unit at 45C or below.
BUNDLE = {
    "size_kw": {"low": 5, "central": 6, "high": 7},
    "max_flow_temp_c": 45,
    "measured_design_load_kw": {"low": 3.73, "central": 4.72, "high": 5.73},
    "htc_w_per_k": {"low": 208.5, "central": 262.4, "high": 318.6},
    "grant_gbp": 7500,
}
QUOTE_C = {
    "label": "Quote C (12 kW)",
    "reading": {
        "heat_pump_make": "Mitsubishi Electric",
        "heat_pump_model": "Ecodan R290 PUZ-WZ120VAA",
        "heat_pump_kw": 12,
        "design_flow_temp_c": 55,
        "buffer_tank": True,
        "total_gbp": 14450,
        "grant_deducted": False,
        "mcs_heat_loss_kw": 8.8,
    },
    "flags": [
        {
            "severity": "red",
            "message": "12 kW quoted, your bills suggest about 4.7 kW: oversized",
            "evidence": "Target size range 5-7 kW from your measured gas use.",
        },
        {
            "severity": "amber",
            "message": "Design flow 55°C: expect higher bills",
            "evidence": "Efficiency (SCOP) falls as flow temperature rises.",
        },
        {
            "severity": "amber",
            "message": "Buffer tank: ask why",
            "evidence": "Most well-designed systems do not need one; it can cut efficiency.",
        },
        {
            "severity": "red",
            "message": "Grant not deducted",
            "evidence": "The Boiler Upgrade Scheme grant should be taken off the price you pay.",
        },
    ],
    "questions": ["Why is a buffer tank needed, and what does it do to efficiency?"],
}


def request(**overrides) -> InstallerDraftsRequest:
    body = {"bundle": BUNDLE, "quotes": [QUOTE_C], "fuse_rating_a": 60, **overrides}
    return InstallerDraftsRequest.model_validate(body)


def context_of(call: Call) -> dict:
    return json.loads(call.input[1]["text"])


def email(body: str, ids: list[str] | None = None) -> callable:
    """A reply that asks for the first right-sized model offered, unless ids are given."""

    def reply(call: Call) -> ArgonEmail:
        offered = context_of(call)["RIGHT_SIZED_MODELS"]
        chosen = ids if ids is not None else [offered[0]["datasheet_id"]]
        named = SEED_IDS[chosen[0]] if chosen and chosen[0] in SEED_IDS else None
        model = f"{named.make} {named.model}" if named else "Acme Heatwave 6"
        return ArgonEmail(
            subject=f"Your quote ({context_of(call)['QUOTE']['label']})",
            body=body.format(model=model),
            requested_model_ids=chosen,
        )

    return reply


GOOD = """Hello,

Thank you for your quote (Quote C (12 kW)). My gas bills put the design heat loss at about 4.7 kW, \
between 3.73 and 5.73 kW, so my target is a 5-7 kW unit. The quote is for 12 kW.

Could you explain the heat loss of 8.8 kW on the quote? Could the system run at 45°C rather \
than 55°C? Why is a buffer tank needed? Is the £7,500 grant deducted from the £14,450 total?

My main fuse is 60 A. Would you re-quote on the {model}?

Kind regards,
[your name]
Property: [your address]"""


def test_traced_numbers_survive() -> None:
    fake = FakeGemini(replies=[email(GOOD)])
    draft = draft_installer_emails(fake, SEED, request()).drafts[0]
    assert draft.source == "argon" and draft.stripped == []
    for figure in ("4.7 kW", "5-7 kW", "45°C", "£7,500", "£14,450", "8.8 kW", "60 A"):
        assert figure in draft.text
    assert draft.text.count("\n\n") >= 3  # paragraphs kept
    assert draft.log[-1].step == "pass"
    assert fake.calls[0].model == "gemini-4-argon"
    assert fake.calls[0].thinking_level == "medium"
    assert fake.calls[0].media_types == []  # text only: no photo ever goes to the drafter


def test_invented_number_sentence_is_stripped() -> None:
    body = GOOD.replace("Why is a buffer", "A 6 kW unit would save me £612 a year. Why is a buffer")
    draft = draft_installer_emails(FakeGemini(replies=[email(body)]), SEED, request()).drafts[0]
    assert draft.source == "argon"
    assert [s.numbers for s in draft.stripped] == [["612"]]
    assert "612" not in draft.text and "Why is a buffer tank needed?" in draft.text
    assert any(not e.passed and "612" in e.check for e in draft.log)


def test_heavy_stripping_falls_back_to_the_template() -> None:
    body = (
        "Hello. Your 14 kW quote costs £19,999. Installs take 23 days. My house loses 6.31 kW. "
        "Would you re-quote on the {model}?\n[your name]"
    )
    req = request()
    draft = draft_installer_emails(FakeGemini(replies=[email(body)]), SEED, req).drafts[0]
    assert draft.source == "template"
    models = right_sized_models(SEED, req.bundle, req.quotes[0])
    assert draft.text == template(req, req.quotes[0], models)
    assert len(draft.stripped) == 3 and "untraceable" in draft.fallback_reason
    assert "[your address]" in draft.text


def test_gemini_failure_falls_back_to_the_template() -> None:
    fake = FakeGemini(replies=[GeminiError("boom")])
    draft = draft_installer_emails(fake, SEED, request()).drafts[0]
    assert draft.source == "template" and draft.fallback_reason
    assert "re-quote on a right-sized heat pump" in draft.text
    assert len(draft.models) >= 2


def test_model_outside_the_library_falls_back() -> None:
    fake = FakeGemini(replies=[email(GOOD, ids=["acme-heatwave-6"])])
    draft = draft_installer_emails(fake, SEED, request()).drafts[0]
    assert draft.source == "template"
    assert "library" in draft.fallback_reason


def test_right_sized_models_are_inside_the_range_and_in_the_library() -> None:
    req = request()
    models = right_sized_models(SEED, req.bundle, req.quotes[0])
    assert 2 <= len(models) <= 3
    for sheet in models:
        assert sheet.id in SEED_IDS and sheet.kind == "heat_pump"
        assert 5 <= sheet.nominal_capacity_kw <= 7
    # The quote's own make leads; then a different make gives the installer a choice.
    assert models[0].make == "Mitsubishi Electric"
    assert len({s.make for s in models}) == len(models)

    fake = FakeGemini(replies=[email(GOOD)])
    draft = draft_installer_emails(fake, SEED, req).drafts[0]
    offered = [m["datasheet_id"] for m in context_of(fake.calls[0])["RIGHT_SIZED_MODELS"]]
    assert offered == [s.id for s in models]
    assert [m.datasheet_id for m in draft.models] == [models[0].id]


def test_drafts_run_per_quote_with_their_own_numbers() -> None:
    quote_a = {"label": "Quote A (6 kW)", "reading": {"heat_pump_kw": 6}, "flags": []}
    seen: dict[str, dict] = {}

    def reply(call: Call) -> ArgonEmail:
        ctx = context_of(call)
        seen[ctx["QUOTE"]["label"]] = ctx
        return email(GOOD)(call)

    fake = FakeGemini(replies=[reply, reply])
    result = draft_installer_emails(fake, SEED, request(quotes=[quote_a, QUOTE_C]))
    assert [d.quote_label for d in result.drafts] == ["Quote A (6 kW)", "Quote C (12 kW)"]
    # Quote A's context has no 14,450 total, so citing it there is untraceable.
    assert any("14,450" in s.numbers for s in result.drafts[0].stripped)
    assert result.drafts[1].stripped == []
    assert seen["Quote A (6 kW)"]["QUOTE"]["flags"] == []


# --- privacy: nothing identifying can enter the request ---------------------------------------


@pytest.mark.parametrize(
    "change",
    [
        lambda b: b.update(address="14 Oakwood Avenue"),
        lambda b: b.update(name="Sam"),
        lambda b: b["bundle"].update(postcode="N10 2AB"),
        lambda b: b["quotes"][0].update(label="sam-smith-quote.pdf"),
        lambda b: b["quotes"][0].update(filename="installer-a.pdf"),
        lambda b: b["quotes"][0]["reading"].update(notes="Customer: S. Smith"),
        lambda b: b["quotes"][0]["reading"].update(meter_number="E12345"),
        lambda b: b["quotes"][0]["reading"].update(line_items=[]),
        lambda b: b["quotes"][0]["flags"][0].update(evidence="Survey at 14 Oak Ave, N10 2AB"),
        lambda b: b["quotes"][0]["questions"].append("Email me at sam@example.com"),
    ],
)
def test_no_identifying_field_can_enter_the_request(gemini, change) -> None:
    body = json.loads(json.dumps({"bundle": BUNDLE, "quotes": [QUOTE_C], "fuse_rating_a": 60}))
    change(body)
    assert client.post("/api/pack/installer-drafts", json=body).status_code == 422
    assert gemini.calls == []


def test_prompt_carries_no_identifying_text(gemini) -> None:
    gemini.replies.append(email(GOOD))
    body = {"bundle": BUNDLE, "quotes": [QUOTE_C], "fuse_rating_a": 60}
    response = client.post("/api/pack/installer-drafts", json=body)
    assert response.status_code == 200
    prompt = gemini.calls[0].prompt
    for leak in ("Oakwood", "N10", "@", ".pdf", "notes", "line_items"):
        assert leak not in prompt
    draft = response.json()["drafts"][0]
    assert draft["source"] == "argon" and "[your address]" in draft["text"]
    assert set(draft["models"][0]) >= {"datasheet_id", "make", "model", "nominal_capacity_kw"}


@pytest.fixture
def gemini():
    fake = FakeGemini()
    app.dependency_overrides[get_gemini] = lambda: fake
    app.dependency_overrides[get_datasheets] = lambda: SEED
    yield fake
    app.dependency_overrides.clear()


client = TestClient(app)


def test_the_quoted_model_is_not_offered_back_as_an_alternative() -> None:
    quote_a = {
        "label": "Quote A (6 kW)",
        "reading": {
            "heat_pump_make": "Mitsubishi Electric",
            "heat_pump_model": "Ecodan R290 PUZ-WZ60VAA",
            "heat_pump_kw": 6,
        },
    }
    req = request(quotes=[quote_a])
    models = right_sized_models(SEED, req.bundle, req.quotes[0])
    assert "mitsubishi-electric-ecodan-r290-puz-wz60vaa" not in {s.id for s in models}
    assert models[0].make == "Mitsubishi Electric"  # the same make's other in-range unit


def test_no_library_model_in_range_still_drafts() -> None:
    req = request(bundle={**BUNDLE, "size_kw": {"low": 3, "central": 3.5, "high": 4}})
    assert right_sized_models(SEED, req.bundle, req.quotes[0]) == []
    body = GOOD.replace(
        "Would you re-quote on the {model}?", "Would you re-quote on a smaller unit?"
    )
    fake = FakeGemini(replies=[email(body, ids=[])])
    draft = draft_installer_emails(fake, SEED, req).drafts[0]
    assert draft.source == "argon" and draft.models == []
    assert context_of(fake.calls[0])["RIGHT_SIZED_MODELS"] == []
