"""The live wrapper's request shape, against a stubbed SDK: no network, no key."""

import json
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from gae.gemini import client as client_module
from gae.gemini.client import GeminiClient, GeminiError, gemini_schema, image, text
from gae.gemini.schemas import ArgonReview, QuoteReading


class StubInteractions:
    def __init__(self, reply: str | Exception):
        self.reply = reply
        self.kwargs: dict = {}

    def create(self, **kwargs):
        self.kwargs = kwargs
        if isinstance(self.reply, Exception):
            raise self.reply
        content = [SimpleNamespace(type="text", text=self.reply)]
        return SimpleNamespace(
            steps=[SimpleNamespace(type="model_output", content=content)],
            output_text=self.reply,
            status="completed",
        )


@pytest.fixture
def stub(monkeypatch: pytest.MonkeyPatch):
    def install(reply: str | Exception) -> StubInteractions:
        interactions = StubInteractions(reply)
        monkeypatch.setattr(
            client_module.genai,
            "Client",
            lambda api_key: SimpleNamespace(interactions=interactions),
        )
        return interactions

    return install


def live(**kwargs) -> GeminiClient:
    return GeminiClient(
        SecretStr("test-key-not-real"),
        lead_model="gemini-4-argon",
        fast_model="gemini-3.8-flash",
        **kwargs,
    )


def test_schema_is_inlined_without_defs_refs_or_defaults() -> None:
    schema = json.dumps(gemini_schema(QuoteReading)) + json.dumps(gemini_schema(ArgonReview))
    assert "$ref" not in schema and "$defs" not in schema and '"default"' not in schema
    items = gemini_schema(QuoteReading)["properties"]["line_items"]["items"]
    assert set(items["properties"]) == {"description", "amount_gbp"}


def test_request_uses_interactions_api_with_thinking_level_only(stub) -> None:
    calls = stub(
        '{"summary": "x", "estimates_explanation": "y", "cited_reason_codes": [],'
        ' "quote_reviews": [], "questions_to_ask": []}'
    )
    result = live().generate(
        model="gemini-4-argon",
        input=[text("hi"), image(b"\xff\xd8", "image/jpeg")],
        schema=ArgonReview,
        thinking_level="high",
        system_instruction="be careful",
    )
    assert result.summary == "x"
    kwargs = calls.kwargs
    assert kwargs["model"] == "gemini-4-argon"
    assert kwargs["generation_config"] == {"thinking_level": "high"}
    assert kwargs["response_format"]["type"] == "text"
    assert kwargs["response_format"]["mime_type"] == "application/json"
    assert kwargs["store"] is False
    assert "background" not in kwargs
    assert kwargs["input"][1] == {"type": "image", "data": "/9g=", "mime_type": "image/jpeg"}
    banned = {"temperature", "top_p", "top_k", "thinking_budget", "cached_content"}
    assert not banned & (set(kwargs) | set(kwargs["generation_config"]))


def test_long_outputs_run_in_background(stub) -> None:
    calls = stub(
        '{"summary": "x", "estimates_explanation": "y", "cited_reason_codes": [],'
        ' "quote_reviews": [], "questions_to_ask": []}'
    )
    live(max_output_tokens=100_000).generate(
        model="gemini-4-argon", input=[text("hi")], schema=ArgonReview, thinking_level="high"
    )
    assert calls.kwargs["background"] is True
    assert calls.kwargs["store"] is True
    assert calls.kwargs["generation_config"]["max_output_tokens"] == 100_000


def test_errors_do_not_echo_request_content(stub) -> None:
    stub(RuntimeError("400 bad request: input contained SECRET-PROMPT-TEXT"))
    with pytest.raises(GeminiError) as err:
        live().generate(
            model="gemini-3.8-flash", input=[text("x")], schema=ArgonReview, thinking_level="low"
        )
    assert "SECRET-PROMPT-TEXT" not in str(err.value)


def test_schema_mismatch_is_a_gemini_error(stub) -> None:
    stub('{"not": "a review"}')
    with pytest.raises(GeminiError, match="did not match ArgonReview"):
        live().generate(
            model="gemini-3.8-flash", input=[text("x")], schema=ArgonReview, thinking_level="low"
        )


def test_repr_never_shows_the_key(stub) -> None:
    stub("{}")
    assert "test-key-not-real" not in repr(live())
