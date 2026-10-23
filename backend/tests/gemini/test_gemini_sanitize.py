"""Server-side metadata strip before Gemini sees an image."""

import base64
from io import BytesIO

from PIL import Image

from gae.gemini.client import FakeGemini
from gae.gemini.extract import glance
from gae.gemini.sanitize import sanitize_image
from gae.gemini.schemas import PhotoGlance, PhotoKind


def _jpeg_with_exif() -> bytes:
    im = Image.new("RGB", (48, 48), color=(120, 80, 40))
    exif = im.getexif()
    exif[0x9286] = "synthetic device and GPS-style metadata"
    exif[0x0132] = "2026:10:23 12:00:00"
    out = BytesIO()
    im.save(out, format="JPEG", exif=exif)
    return out.getvalue()


def test_sanitize_strips_exif_including_gps_pointer() -> None:
    data = _jpeg_with_exif()
    with Image.open(BytesIO(data)) as before:
        assert before.getexif()

    clean, mime = sanitize_image(data, "image/jpeg")
    assert mime == "image/jpeg"
    with Image.open(BytesIO(clean)) as after:
        assert not after.getexif()
        assert "exif" not in after.info


def test_glance_request_image_has_no_exif_after_upload_path() -> None:
    data = _jpeg_with_exif()
    gemini = FakeGemini(
        [
            PhotoGlance(
                detected_kind="boiler_plate",
                legible=True,
                key_fields=[],
                confidence="high",
                summary="ok",
                retake_hint=None,
                face_visible=False,
                number_plate_visible=False,
                house_or_street_visible=False,
                mail_or_envelope_visible=False,
                name_address_or_meter_visible=False,
            )
        ]
    )
    glance(gemini, PhotoKind.BOILER_PLATE, data, "image/jpeg")
    (call,) = gemini.calls
    image_block = next(b for b in call.input if b["type"] == "image")
    payload = base64.b64decode(image_block["data"])
    with Image.open(BytesIO(payload)) as sent:
        assert not sent.getexif()
