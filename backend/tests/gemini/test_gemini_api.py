"""Routes, with Gemini and the datasheet library overridden: no network, no keys, no Atlas."""

import base64

import pytest
from fastapi.testclient import TestClient

from gae.gemini.client import FakeGemini, GeminiError
from gae.gemini.router import get_datasheets, get_gemini
from gae.gemini.schemas import PhotoGlance
from gae.main import app
from gae.settings import Settings, get_settings
from tests.gemini.conftest import JPEG, PDF, boiler, quote
from tests.gemini.test_gemini_review import argon_reply


@pytest.fixture
def gemini(lookup):
    fake = FakeGemini()
    app.dependency_overrides[get_gemini] = lambda: fake
    app.dependency_overrides[get_datasheets] = lambda: lookup
    yield fake
    app.dependency_overrides.clear()


client = TestClient(app)


def photo(kind: str = "boiler_plate", data: bytes = JPEG, mime: str = "image/jpeg"):
    return {"data": {"kind": kind}, "files": {"file": ("plate.jpg", data, mime)}}


def test_photo_check_matches_frontend_shape(gemini) -> None:
    gemini.replies.append(
        PhotoGlance(
            detected_kind="boiler_plate",
            legible=True,
            key_fields=[{"name": "output_kw", "value": "24"}],
            confidence="high",
            summary="legible, 24 kW Acme",
            retake_hint=None,
            face_visible=False,
            number_plate_visible=False,
        )
    )
    body = client.post("/api/photos/check", **photo()).json()
    frontend_fields = {
        "kind",
        "legible",
        "summary",
        "key_fields",
        "confidence",
        "retake_hint",
        "privacy_warning",
    }
    assert frontend_fields <= set(body)
    assert body["kind"] == "boiler_plate" and body["key_fields"] == {"output_kw": "24"}


def test_extract_returns_full_reading_and_log(gemini) -> None:
    gemini.replies.append(boiler())
    body = client.post("/api/photos/extract", **photo()).json()
    assert body["status"] == "verified"
    assert body["reading"]["heating_output_kw"] == 20.0  # subclass fields survive serialisation
    entry = body["log"][0]
    assert {"id", "step", "input", "model", "check", "passed", "action", "at"} <= set(entry)


def test_quotes_check_flags_each_upload(gemini) -> None:
    gemini.replies.append(quote())
    response = client.post(
        "/api/quotes/check",
        data={"size_low_kw": "5", "size_high_kw": "7", "design_load_kw": "4.7"},
        files=[("quotes", ("quote-9kw.pdf", PDF, "application/pdf"))],
    )
    (result,) = response.json()
    assert result["filename"] == "quote-9kw.pdf" and result["quoted_kw"] == 9.0
    assert any(f["message"].endswith("oversized") for f in result["flags"])


def test_review_route(gemini, sam_maths) -> None:
    gemini.replies.append(argon_reply(sam_maths))
    body = {
        "photos": [
            {
                "kind": "boiler_plate",
                "data_base64": base64.b64encode(JPEG).decode(),
                "mime_type": "image/jpeg",
            }
        ],
        "quotes": [{"quote_id": "Quote A", "reading": quote().model_dump(mode="json")}],
        "maths": sam_maths.model_dump(mode="json"),
    }
    result = client.post("/api/review", json=body).json()
    assert result["model"] == "gemini-4-argon"
    assert result["stripped"]
    assert "advises; you decide" in result["disclaimer"]


def test_rejects_non_image_uploads(gemini) -> None:
    response = client.post(
        "/api/photos/check", **photo(data=b"MZ", mime="application/x-msdownload")
    )
    assert response.status_code == 415
    assert gemini.calls == []


def test_gemini_failure_is_a_clean_502(gemini) -> None:
    gemini.replies.append(GeminiError("upstream said: SECRET-DETAIL"))
    response = client.post("/api/photos/check", **photo())
    assert response.status_code == 502
    assert "SECRET-DETAIL" not in response.text


def test_without_a_key_routes_say_not_configured() -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, gemini_api_key=None)
    try:
        response = client.post("/api/photos/check", **photo())
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 503
