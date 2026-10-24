"""The live wrapper's request shape, against a stubbed SDK: no network, no key."""

import json
from types import SimpleNamespace

import httpx
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


def test_large_video_uses_files_api_and_deletes_immediately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uploaded: list[str] = []
    deleted: list[str] = []
    interactions = StubInteractions(
        '{"summary": "x", "estimates_explanation": "y", "cited_reason_codes": [],'
        ' "quote_reviews": [], "questions_to_ask": []}'
    )

    class StubFiles:
        def upload(self, *, file, config):
            uploaded.append(config["mime_type"])
            return SimpleNamespace(
                name="files/temp-123", uri="https://generativelanguage/files/123"
            )

        def delete(self, *, name):
            deleted.append(name)

    monkeypatch.setattr(
        client_module.genai,
        "Client",
        lambda api_key: SimpleNamespace(interactions=interactions, files=StubFiles()),
    )
    monkeypatch.setattr(client_module, "INLINE_VIDEO_MAX_BYTES", 8)

    live().generate(
        model="gemini-4-argon",
        input=[text("watch"), client_module.video(b"0123456789abcdef", "video/mp4")],
        schema=ArgonReview,
        thinking_level="high",
    )
    assert uploaded == ["video/mp4"]
    assert deleted == ["files/temp-123"]
    assert interactions.kwargs["input"][1] == {
        "type": "video",
        "uri": "https://generativelanguage/files/123",
        "mime_type": "video/mp4",
    }


def test_sdk_retries_disabled_so_429_and_timeouts_fail_fast(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Real `genai.Client` with mocked transport: no 3x retries or 30 s `Retry-After` sleep."""
    monkeypatch.setattr(
        "time.sleep",
        lambda s: (_ for _ in ()).throw(AssertionError(f"unexpected sleep({s})")),
    )
    requests_seen: list[httpx.Request] = []

    def rate_limited(request: httpx.Request) -> httpx.Response:
        requests_seen.append(request)
        return httpx.Response(
            429,
            headers={"Retry-After": "30", "Content-Type": "application/json"},
            json={"error": {"message": "Quota exceeded", "code": "too_many_requests"}},
            request=request,
        )

    client = live()
    assert client._client.interactions.sdk_configuration.retry_config.strategy == "none"
    client._client._api_client._httpx_client._transport = httpx.MockTransport(rate_limited)
    capsys.readouterr()

    with pytest.raises(GeminiError, match="RateLimitError") as exc_info:
        client.generate(
            model="gemini-3.8-flash",
            input=[text("check radiator")],
            schema=ArgonReview,
            thinking_level="low",
            timeout_s=15.0,
            purpose="/api/photos/check:radiators",
        )
    assert exc_info.value.upstream_status == 429
    assert len(requests_seen) == 1
    log_record = json.loads(capsys.readouterr().out.strip())
    assert log_record["outcome"] == "RateLimitError"
    assert log_record["error_class"] == "RateLimitError"
    assert log_record["upstream_status"] == 429
    assert log_record["attempts"] == 1

    timeouts_seen: list[dict] = []

    def timed_out(request: httpx.Request) -> httpx.Response:
        timeouts_seen.append(dict(request.extensions.get("timeout", {})))
        raise httpx.ReadTimeout("timed out", request=request)

    client._client._api_client._httpx_client._transport = httpx.MockTransport(timed_out)
    with pytest.raises(GeminiError, match="APITimeoutError"):
        client.generate(
            model="gemini-3.8-flash",
            input=[text("check radiator")],
            schema=ArgonReview,
            thinking_level="low",
            timeout_s=15.0,
            purpose="/api/photos/check:radiators",
        )
    assert len(timeouts_seen) == 1
    assert timeouts_seen[0]["read"] == 15.0
    timeout_record = json.loads(capsys.readouterr().out.strip())
    assert timeout_record["outcome"] == "timeout"
    assert timeout_record["error_class"] == "APITimeoutError"
    assert timeout_record["upstream_status"] is None
    assert timeout_record["attempts"] == 1


def test_structured_stdout_log_has_only_allowed_fields_for_success_and_failure(
    stub, capsys: pytest.CaptureFixture[str]
) -> None:
    allowed_success_fields = {
        "severity",
        "message",
        "purpose",
        "model",
        "thinking_level",
        "latency_ms",
        "outcome",
        "attempts",
    }
    allowed_error_fields = allowed_success_fields | {"error_class", "upstream_status"}
    forbidden_tokens = (
        "SECRET-PROMPT-TEXT",
        "SECRET-MODEL-OUTPUT",
        "SW1A 1AA",
        "10 Downing Street",
        "100023336956",
        "0000-1111-2222-3333-4444",
        "radiator-photo.jpg",
        "test-key-not-real",
    )

    stub(
        '{"summary": "SECRET-MODEL-OUTPUT", "estimates_explanation": "y",'
        ' "cited_reason_codes": [], "quote_reviews": [], "questions_to_ask": []}'
    )
    capsys.readouterr()
    live().generate(
        model="gemini-3.8-flash",
        input=[
            text(
                "SECRET-PROMPT-TEXT SW1A 1AA 10 Downing Street "
                "100023336956 0000-1111-2222-3333-4444 radiator-photo.jpg"
            ),
            image(b"\xff\xd8secret-bytes", "image/jpeg"),
        ],
        schema=ArgonReview,
        thinking_level="low",
        timeout_s=15.0,
        purpose="/api/photos/check:radiators",
    )
    out_lines = capsys.readouterr().out.strip().splitlines()
    assert len(out_lines) == 1
    ok_record = json.loads(out_lines[0])
    assert set(ok_record) == allowed_success_fields
    assert ok_record["severity"] == "INFO"
    assert ok_record["purpose"] == "/api/photos/check:radiators"
    assert ok_record["model"] == "gemini-3.8-flash"
    assert ok_record["thinking_level"] == "low"
    assert isinstance(ok_record["latency_ms"], int) and ok_record["latency_ms"] >= 0
    assert ok_record["outcome"] == "ok"
    assert ok_record["attempts"] == 1
    for token in forbidden_tokens:
        assert token not in out_lines[0]

    class UpstreamError(RuntimeError):
        status_code = 503

    stub(
        UpstreamError(
            "503 unavailable for SECRET-PROMPT-TEXT SW1A 1AA 10 Downing Street "
            "100023336956 0000-1111-2222-3333-4444 radiator-photo.jpg test-key-not-real"
        )
    )
    with pytest.raises(GeminiError):
        live().generate(
            model="gemini-3.8-flash",
            input=[text("SECRET-PROMPT-TEXT")],
            schema=ArgonReview,
            thinking_level="low",
            timeout_s=15.0,
            purpose="/api/photos/check:radiators",
        )
    err_lines = capsys.readouterr().out.strip().splitlines()
    assert len(err_lines) == 1
    err_record = json.loads(err_lines[0])
    assert set(err_record) == allowed_error_fields
    assert err_record["severity"] == "ERROR"
    assert err_record["purpose"] == "/api/photos/check:radiators"
    assert err_record["model"] == "gemini-3.8-flash"
    assert err_record["thinking_level"] == "low"
    assert isinstance(err_record["latency_ms"], int) and err_record["latency_ms"] >= 0
    assert err_record["outcome"] == "UpstreamError"
    assert err_record["attempts"] == 1
    assert err_record["error_class"] == "UpstreamError"
    assert err_record["upstream_status"] == 503
    for token in forbidden_tokens:
        assert token not in err_lines[0]

    stub('{"not_valid": "SECRET-MODEL-OUTPUT"}')
    with pytest.raises(GeminiError, match="did not match ArgonReview"):
        live().generate(
            model="gemini-4-argon",
            input=[text("SECRET-PROMPT-TEXT")],
            schema=ArgonReview,
            thinking_level="high",
            purpose="/api/photos/extract:boiler_plate",
            attempt=2,
        )
    val_lines = capsys.readouterr().out.strip().splitlines()
    assert len(val_lines) == 1
    val_record = json.loads(val_lines[0])
    assert set(val_record) == allowed_error_fields
    assert val_record["outcome"] == "validation_failure"
    assert val_record["error_class"] == "ValidationError"
    assert val_record["upstream_status"] is None
    assert val_record["attempts"] == 2
    for token in forbidden_tokens:
        assert token not in val_lines[0]
