"""Routes, with Gemini and the datasheet library overridden: no network, no keys, no Atlas."""

import base64
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

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
            house_or_street_visible=False,
            mail_or_envelope_visible=False,
            name_address_or_meter_visible=False,
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
        data={
            "quote_index": "0",
            "quote_name": "quote-9kw.pdf",
            "size_low_kw": "5",
            "size_high_kw": "7",
            "design_load_kw": "4.7",
        },
        files=[("quotes", ("quote-9kw.pdf", PDF, "application/pdf"))],
    )
    (result,) = response.json()
    assert result["filename"] == "quote-9kw.pdf" and result["quoted_kw"] == 9.0
    assert any(f["message"].endswith("oversized") for f in result["flags"])


def test_quotes_check_groups_pages_into_one_quote(gemini) -> None:
    gemini.replies.append(quote())
    files = [("quotes", (f"page-{i}.jpg", JPEG, "image/jpeg")) for i in range(3)]
    response = client.post(
        "/api/quotes/check",
        data={
            "quote_index": ["0", "0", "0"],
            "quote_name": ["installer-a.pdf", "installer-a.pdf", "installer-a.pdf"],
        },
        files=files,
    )
    assert response.status_code == 200
    (result,) = response.json()
    assert result["filename"] == "installer-a.pdf"
    (call,) = gemini.calls
    assert call.media_types.count("image") == 3


def _redacted_page(shade: int) -> bytes:
    """A synthetic page as the browser cover-up exports it: 892x1262 (A4 at scale 1.5), JPEG 0.9."""
    im = Image.new("RGB", (892, 1262), color=(255, 255, 255))
    ImageDraw.Draw(im).rectangle((72, 340, 820, 700), fill=(shade, shade, shade))
    out = BytesIO()
    im.save(out, format="JPEG", quality=90)
    return out.getvalue()


def test_quote_pages_reach_the_reader_distinct_in_order_at_browser_size(gemini) -> None:
    # Regression: the browser once sent page 1 twice, so the price page never reached Gemini
    # and a readable quote came back "couldn't tell". The route must pass each page through.
    gemini.replies.append(quote())
    pages = [_redacted_page(40), _redacted_page(200)]
    response = client.post(
        "/api/quotes/check",
        data={"quote_index": ["0", "0"], "quote_name": ["Quote A", "Quote A"]},
        files=[("quotes", (f"p{i}.jpg", page, "image/jpeg")) for i, page in enumerate(pages)],
    )
    assert response.status_code == 200
    (call,) = gemini.calls
    images = [base64.b64decode(b["data"]) for b in call.input if b["type"] == "image"]
    assert len(images) == 2 and images[0] != images[1]
    shades = []
    for data in images:
        with Image.open(BytesIO(data)) as im:
            assert im.size == (892, 1262)
            shades.append(im.convert("L").getpixel((400, 500)))
    assert shades[0] < 100 < shades[1]
    assert "These 2 images are sequential pages of one installer quote" in call.prompt


def test_three_three_page_quotes_return_three_results(gemini) -> None:
    gemini.replies.extend([quote(), quote(), quote()])
    files = []
    quote_index = []
    quote_name = []
    for q in range(3):
        for p in range(3):
            files.append(("quotes", (f"q{q}-p{p}.jpg", JPEG, "image/jpeg")))
            quote_index.append(str(q))
            quote_name.append(f"quote-{q}.pdf")
    response = client.post(
        "/api/quotes/check",
        data={"quote_index": quote_index, "quote_name": quote_name},
        files=files,
    )
    assert response.status_code == 200
    results = response.json()
    assert len(results) == 3
    assert {r["filename"] for r in results} == {
        "quote-0.pdf",
        "quote-1.pdf",
        "quote-2.pdf",
    }
    assert len(gemini.calls) == 3


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
    assert response.json()["detail"] == "Gemini couldn't read this right now; please try again"


def test_gemini_quota_failure_gives_distinct_message(gemini) -> None:
    gemini.replies.append(
        GeminiError(
            "Your billing account has exceeded its monthly spending cap",
            upstream_status=429,
        )
    )
    response = client.post("/api/photos/check", **photo())
    assert response.status_code == 502
    assert "Gemini quota/billing limit reached" in response.json()["detail"]
    assert "Your billing account" not in response.text


def test_without_a_key_routes_say_not_configured() -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, gemini_api_key=None)
    try:
        response = client.post("/api/photos/check", **photo())
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 503
