"""Thin wrapper over the `google-genai` Interactions API, plus a scripted fake for tests.

Every call is `client.interactions.create(model=..., input=..., generation_config=
{"thinking_level": ...}, response_format={"type": "text", "mime_type": "application/json",
"schema": ...})` and the reply is validated into a pydantic model. Hackathon rules: no
temperature, top_p, top_k, thinking_budget or cached_content anywhere; `background=True` only
for outputs past 65,536 tokens.

Privacy: calls use `store=False`, so Google does not retain the homeowner's photos, bills or
quotes as stored interactions. That also rules out `previous_interaction_id`, so a re-read
sends the image again rather than chaining turns.
"""

import base64
import contextlib
import io
import json
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

import httpx
from google import genai
from google.genai._gaos.utils import RetryConfig
from pydantic import BaseModel, SecretStr, ValidationError

ThinkingLevel = Literal["low", "medium", "high"]
Block = dict[str, Any]

# Past this many output tokens Gemini 4 Argon needs background execution.
LONG_DECODE_TOKENS = 65_536
# Inline request payloads must stay under the 20 MB API limit; larger clips use Files API
# upload and are deleted immediately in a `finally` block.
INLINE_VIDEO_MAX_BYTES = 18 * 1024 * 1024


class GeminiError(RuntimeError):
    """A Gemini call failed. Messages never include request content or the key."""

    def __init__(self, message: str, *, upstream_status: int | None = None):
        super().__init__(message)
        self.upstream_status = upstream_status


class GeminiNotConfigured(GeminiError):
    pass


def text(value: str) -> Block:
    return {"type": "text", "text": value}


def image(data: bytes, mime_type: str) -> Block:
    """Inline image, kept in memory for this request only."""
    return {"type": "image", "data": base64.b64encode(data).decode("ascii"), "mime_type": mime_type}


def document(data: bytes, mime_type: str = "application/pdf") -> Block:
    return {
        "type": "document",
        "data": base64.b64encode(data).decode("ascii"),
        "mime_type": mime_type,
    }


def video(data: bytes, mime_type: str = "video/mp4") -> Block:
    """Inline video, kept in memory for this request only."""
    return {
        "type": "video",
        "data": base64.b64encode(data).decode("ascii"),
        "mime_type": mime_type,
    }


def gemini_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Pydantic JSON schema with `$ref`s inlined and `default`s dropped.

    The structured-output docs list `$ref: "#"` only for recursion and do not document
    `$defs`, so nested models are inlined to stay inside the supported subset.
    """
    raw = model.model_json_schema()
    defs = raw.pop("$defs", {})

    def inline(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                target = defs[node["$ref"].rsplit("/", 1)[-1]]
                extra = {k: v for k, v in node.items() if k != "$ref"}
                return inline({**target, **extra})
            out = {k: inline(v) for k, v in node.items() if k != "default"}
            if isinstance(out.get("properties"), dict):
                out["required"] = list(out["properties"].keys())
            return out
        if isinstance(node, list):
            return [inline(item) for item in node]
        return node

    return inline(raw)


class StructuredModel(Protocol):
    """What the extractors and review need: one structured reply per call."""

    lead_model: str
    fast_model: str

    def generate[T: BaseModel](
        self,
        *,
        model: str,
        input: Sequence[Block],
        schema: type[T],
        thinking_level: ThinkingLevel,
        system_instruction: str | None = None,
        timeout_s: float = 60.0,
        purpose: str = "generate",
        attempt: int = 1,
    ) -> T: ...


class GeminiClient:
    def __init__(
        self,
        api_key: SecretStr,
        *,
        lead_model: str,
        fast_model: str,
        max_output_tokens: int | None = None,
    ):
        if not api_key.get_secret_value().strip():
            raise GeminiNotConfigured("GEMINI_API_KEY is not set")
        self._client = genai.Client(api_key=api_key.get_secret_value())
        # `GeminiNextGenInteractions` otherwise defaults to 3 retries (`max_retries=3`, 4 attempts)
        # and sleeps for the full upstream `Retry-After` header (e.g. 30 s per 429), turning a
        # 15 s check into a ~96 s hang. Fail fast on a single attempt so callers control retries.
        sdk_config = getattr(self._client.interactions, "sdk_configuration", None)
        if sdk_config is not None:
            sdk_config.retry_config = RetryConfig("none", None, False)
        self.lead_model = lead_model
        self.fast_model = fast_model
        self.max_output_tokens = max_output_tokens

    def __repr__(self) -> str:
        return f"GeminiClient(lead_model={self.lead_model!r}, fast_model={self.fast_model!r})"

    def generate[T: BaseModel](
        self,
        *,
        model: str,
        input: Sequence[Block],
        schema: type[T],
        thinking_level: ThinkingLevel,
        system_instruction: str | None = None,
        timeout_s: float = 60.0,
        purpose: str = "generate",
        attempt: int = 1,
    ) -> T:
        started = time.monotonic()
        deadline = started + timeout_s
        outcome = "ok"
        error_class: str | None = None
        upstream_status: int | None = None
        config: dict[str, Any] = {"thinking_level": thinking_level}
        long_decode = (self.max_output_tokens or 0) > LONG_DECODE_TOKENS
        if self.max_output_tokens:
            config["max_output_tokens"] = self.max_output_tokens
        kwargs: dict[str, Any] = {
            "model": model,
            "input": list(input),
            "generation_config": config,
            "response_format": {
                "type": "text",
                "mime_type": "application/json",
                "schema": gemini_schema(schema),
            },
            # Background execution needs a stored interaction to poll; nothing else is stored.
            "store": long_decode,
            "timeout": timeout_s,
        }
        if long_decode:
            kwargs["background"] = True
        if system_instruction:
            kwargs["system_instruction"] = system_instruction
        uploaded_names: list[str] = []
        try:
            try:
                kwargs["input"] = self._prepare_inputs(input, uploaded_names, deadline)
                if uploaded_names:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError("Gemini call timed out during file upload")
                    kwargs["timeout"] = remaining
                interaction = self._client.interactions.create(**kwargs)
                if long_decode:
                    interaction = self._wait(interaction, deadline)
            except GeminiError as exc:
                error_class = type(exc).__name__
                upstream_status = exc.upstream_status
                outcome = "timeout" if "timed out" in str(exc) else error_class
                raise
            except Exception as exc:
                error_class = type(exc).__name__
                upstream_status = _upstream_status(exc)
                outcome = "timeout" if _is_timeout(exc, upstream_status) else error_class
                # The SDK's message can echo request fields; keep only the type.
                raise GeminiError(
                    f"Gemini call to {model} failed ({error_class})",
                    upstream_status=upstream_status,
                ) from None
            finally:
                for name in uploaded_names:
                    with contextlib.suppress(Exception):
                        self._client.files.delete(name=name)
            reply = _output_text(interaction)
            if not reply:
                outcome = "validation_failure"
                error_class = "GeminiError"
                raise GeminiError(f"{model} returned no text")
            try:
                return schema.model_validate_json(reply)
            except ValidationError:
                outcome = "validation_failure"
                error_class = "ValidationError"
                raise GeminiError(f"{model} reply did not match {schema.__name__}") from None
        finally:
            _log_gemini_call(
                purpose=purpose,
                model=model,
                thinking_level=thinking_level,
                latency_ms=round((time.monotonic() - started) * 1000),
                outcome=outcome,
                attempts=attempt,
                error_class=error_class,
                upstream_status=upstream_status,
            )

    def _prepare_inputs(
        self, input: Sequence[Block], uploaded_names: list[str], deadline: float
    ) -> list[Block]:
        """Keep video inline under 18 MB; use Files API above that and record for deletion."""
        prepared: list[Block] = []
        max_b64_len = (INLINE_VIDEO_MAX_BYTES * 4) // 3
        for block in input:
            if (
                block.get("type") == "video"
                and isinstance(block.get("data"), str)
                and len(block["data"]) > max_b64_len
            ):
                raw = base64.b64decode(block["data"])
                mime_type = str(block.get("mime_type") or "video/mp4")
                uploaded = self._client.files.upload(
                    file=io.BytesIO(raw),
                    config={"mime_type": mime_type},
                )
                name = getattr(uploaded, "name", None)
                if not name:
                    raise GeminiError("Files API upload returned no file name")
                uploaded_names.append(str(name))
                state = _file_state(uploaded)
                while "PROCESSING" in state:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError("Uploaded video processing timed out")
                    time.sleep(min(1.0, remaining))
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Uploaded video processing timed out")
                    uploaded = self._client.files.get(name=name)
                    state = _file_state(uploaded)
                if "FAILED" in state:
                    raise GeminiError(f"Uploaded video processing ended {state}")
                uri = getattr(uploaded, "uri", None)
                if not uri:
                    raise GeminiError("Files API upload returned no URI")
                prepared.append({"type": "video", "uri": str(uri), "mime_type": mime_type})
            else:
                prepared.append(block)
        return prepared

    def _wait(self, interaction: Any, deadline: float) -> Any:
        while interaction.status in ("in_progress", "queued"):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Background interaction timed out")
            time.sleep(min(5.0, remaining))
            if time.monotonic() >= deadline:
                raise TimeoutError("Background interaction timed out")
            interaction = self._client.interactions.get(id=interaction.id)
        if interaction.status != "completed":
            raise GeminiError(f"Background interaction ended {interaction.status}")
        return interaction


def _upstream_status(exc: BaseException) -> int | None:
    for candidate in (
        getattr(exc, "status_code", None),
        getattr(exc, "code", None),
        getattr(getattr(exc, "response", None), "status_code", None),
    ):
        if isinstance(candidate, int) and not isinstance(candidate, bool):
            return candidate
    return None


def _is_timeout(exc: BaseException, status: int | None) -> bool:
    if isinstance(exc, TimeoutError | httpx.TimeoutException):
        return True
    if "Timeout" in type(exc).__name__:
        return True
    return status in (408, 504)


def _log_gemini_call(
    *,
    purpose: str,
    model: str,
    thinking_level: ThinkingLevel,
    latency_ms: int,
    outcome: str,
    attempts: int,
    error_class: str | None = None,
    upstream_status: int | None = None,
) -> None:
    """Emit one structured JSON log line to stdout per Gemini call (no content or PII)."""
    record: dict[str, Any] = {
        "severity": "INFO" if outcome == "ok" else "ERROR",
        "message": f"gemini {purpose} {outcome}",
        "purpose": purpose,
        "model": model,
        "thinking_level": thinking_level,
        "latency_ms": latency_ms,
        "outcome": outcome,
        "attempts": attempts,
    }
    if outcome != "ok":
        record["error_class"] = error_class
        record["upstream_status"] = upstream_status
    print(json.dumps(record), file=sys.stdout, flush=True)


def _file_state(uploaded: Any) -> str:
    state = getattr(uploaded, "state", None)
    name = getattr(state, "name", None)
    return str(name or state or "").upper()


def _output_text(interaction: Any) -> str:
    """Text across every `model_output` step: long decode adds one step per continuation."""
    parts = [
        content.text
        for step in interaction.steps or []
        if step.type == "model_output"
        for content in step.content or []
        if content.type == "text" and content.text
    ]
    return "".join(parts) or (interaction.output_text or "")


@dataclass
class Call:
    model: str
    schema: str
    thinking_level: ThinkingLevel
    input: list[Block]
    system_instruction: str | None
    purpose: str = "generate"
    attempt: int = 1

    @property
    def prompt(self) -> str:
        return "\n".join(b["text"] for b in self.input if b["type"] == "text")

    @property
    def media_types(self) -> list[str]:
        return [b["type"] for b in self.input if b["type"] != "text"]


Reply = BaseModel | dict[str, Any] | Exception | Callable[[Call], BaseModel | dict[str, Any]]


@dataclass
class FakeGemini:
    """Scripted `StructuredModel`: replies are consumed in order and every call is recorded."""

    replies: list[Reply] = field(default_factory=list)
    lead_model: str = "gemini-4-argon"
    fast_model: str = "gemini-3.8-flash"
    calls: list[Call] = field(default_factory=list)

    def generate[T: BaseModel](
        self,
        *,
        model: str,
        input: Sequence[Block],
        schema: type[T],
        thinking_level: ThinkingLevel,
        system_instruction: str | None = None,
        timeout_s: float = 60.0,
        purpose: str = "generate",
        attempt: int = 1,
    ) -> T:
        call = Call(
            model,
            schema.__name__,
            thinking_level,
            list(input),
            system_instruction,
            purpose=purpose,
            attempt=attempt,
        )
        self.calls.append(call)
        if not self.replies:
            raise AssertionError(f"FakeGemini has no reply left for {schema.__name__}")
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        if callable(reply):
            reply = reply(call)
        # Round-trip through JSON like the live client, so schema drift fails tests.
        payload = reply.model_dump_json() if isinstance(reply, BaseModel) else reply
        if isinstance(payload, dict):
            return schema.model_validate(payload)
        return schema.model_validate_json(payload)
