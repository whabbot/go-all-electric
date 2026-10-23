"""Radiator walk-through video: metadata strip, caps, verification loop and photo requests."""

import base64
import struct

import pytest
from fastapi.testclient import TestClient

from gae.gemini import video as video_module
from gae.gemini.client import FakeGemini
from gae.gemini.router import get_datasheets, get_gemini
from gae.gemini.schemas import RadiatorVideoReading, VideoRadiator
from gae.gemini.video import (
    MAX_VIDEO_DURATION_S,
    apply_radiator_spec_checks,
    extract_radiator_video,
    sanitize_video,
)
from gae.main import app


def _box(box_type: bytes, payload: bytes) -> bytes:
    return struct.pack(">I4s", 8 + len(payload), box_type) + payload


def _mvhd(
    *,
    timescale: int = 1000,
    duration: int = 18_000,
    creation_time: int = 3_800_000_000,
    modification_time: int = 3_800_000_100,
) -> bytes:
    version_flags = struct.pack(">I", 0)
    header = struct.pack(">IIII", creation_time, modification_time, timescale, duration)
    rest = b"\x00" * 80
    return _box(b"mvhd", version_flags + header + rest)


def _tkhd(
    *,
    duration: int = 18_000,
    creation_time: int = 3_800_000_000,
    modification_time: int = 3_800_000_100,
) -> bytes:
    version_flags = struct.pack(">I", 1)
    header = struct.pack(">IIIII", creation_time, modification_time, 1, 0, duration)
    rest = b"\x00" * 60
    return _box(b"tkhd", version_flags + header + rest)


def _mdhd(
    *,
    timescale: int = 1000,
    duration: int = 18_000,
    creation_time: int = 3_800_000_000,
    modification_time: int = 3_800_000_100,
) -> bytes:
    version_flags = struct.pack(">I", 0)
    header = struct.pack(">IIII", creation_time, modification_time, timescale, duration)
    rest = b"\x00" * 4
    return _box(b"mdhd", version_flags + header + rest)


def _hdlr(name: bytes = b"CoreMedia Video\x00") -> bytes:
    prefix = b"\x00" * 8 + b"vide" + b"\x00" * 12
    return _box(b"hdlr", prefix + name)


def _synthetic_mp4(*, duration_ms: int = 18_000, include_gps: bool = True) -> bytes:
    ftyp = _box(b"ftyp", b"mp42\x00\x00\x00\x00mp42isom")
    mdia = _box(b"mdia", _mdhd(duration=duration_ms) + _hdlr())
    trak = _box(b"trak", _tkhd(duration=duration_ms) + mdia)
    children = [_mvhd(duration=duration_ms), trak]
    if include_gps:
        xyz = _box(b"\xa9xyz", b"\x00\x12\x15\xc7+51.5200-000.0900/")
        mod = _box(b"\xa9mod", b"iPhone 17 Pro")
        udta = _box(b"udta", xyz + mod)
        meta_payload = (
            b"\x00\x00\x00\x00"
            + _box(b"keys", b"com.apple.quicktime.location.ISO6709")
            + _box(b"ilst", b"+51.5200-000.0900/")
        )
        meta = _box(b"meta", meta_payload)
        children.extend([udta, meta])
    moov = _box(b"moov", b"".join(children))
    uuid_box = _box(b"uuid", b"SECRET-UUID-DEVICE-TAG-1234567890") if include_gps else b""
    mdat = _box(b"mdat", b"\x00\x00\x00\x04synthetic-video-frames")
    return ftyp + moov + uuid_box + mdat


def _rad(**overrides) -> VideoRadiator:
    values = dict(
        legible=True,
        confidence="high",
        notes="",
        first_seen="0:03",
        last_seen="0:07",
        room="Living room",
        radiator_type="K2",
        panels=2,
        fin_rows=2,
        height_mm=600,
        width_mm=1200,
        could_not_judge=[],
    )
    return VideoRadiator(**{**values, **overrides})


def _video_reading(radiators: list[VideoRadiator], **overrides) -> RadiatorVideoReading:
    values = dict(
        legible=True,
        confidence="high",
        notes="",
        radiator_count=len(radiators),
        radiators=radiators,
        could_not_judge=[],
    )
    return RadiatorVideoReading(**{**values, **overrides})


# --- privacy: metadata strip & size/length caps ----------------------------------------------


def test_metadata_stripped_before_gemini_request() -> None:
    raw = _synthetic_mp4(include_gps=True)
    for marker in (
        b"+51.5200-000.0900/",
        b"iPhone 17 Pro",
        b"com.apple.quicktime.location.ISO6709",
        b"SECRET-UUID-DEVICE-TAG-1234567890",
        b"CoreMedia Video",
    ):
        assert marker in raw

    gemini = FakeGemini([_video_reading([_rad()])])
    extract_radiator_video(gemini, raw, "video/mp4")

    (call,) = gemini.calls
    video_block = next(b for b in call.input if b["type"] == "video")
    sent = base64.b64decode(video_block["data"])

    for forbidden in (
        b"+51.5200-000.0900/",
        b"iPhone 17 Pro",
        b"com.apple.quicktime.location.ISO6709",
        b"SECRET-UUID-DEVICE-TAG-1234567890",
        b"CoreMedia Video",
        b"\xa9xyz",
        b"\xa9mod",
        b"udta",
        b"meta",
    ):
        assert forbidden not in sent
    # Creation and modification timestamps in mvhd/tkhd/mdhd are zeroed out.
    assert struct.pack(">I", 3_800_000_000) not in sent
    assert struct.pack(">I", 3_800_000_100) not in sent
    # Media payload remains intact.
    assert b"synthetic-video-frames" in sent


def test_size_and_duration_caps(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError, match="Video is empty"):
        sanitize_video(b"", "video/mp4")

    with pytest.raises(ValueError, match="MP4, MOV or WebM"):
        sanitize_video(b"not-a-video", "text/plain")

    too_long = _synthetic_mp4(duration_ms=int((MAX_VIDEO_DURATION_S + 5) * 1000))
    with pytest.raises(ValueError, match="maximum length is 90 seconds"):
        sanitize_video(too_long, "video/mp4")

    monkeypatch.setattr(video_module, "MAX_VIDEO_BYTES", 64)
    with pytest.raises(ValueError, match="exceeds the 100 MB limit"):
        sanitize_video(_synthetic_mp4(duration_ms=10_000), "video/mp4")


# --- verification loop: count, de-dup, re-ask, photo requests --------------------------------


def test_clean_video_verifies_on_argon_high_and_feeds_spec_check() -> None:
    r1 = _rad(
        first_seen="0:03",
        last_seen="0:07",
        room="Living room",
        radiator_type="K2",
        panels=2,
        fin_rows=2,
        height_mm=600,
        width_mm=2000,
    )
    r2 = _rad(
        first_seen="0:15",
        last_seen="0:20",
        room="Bedroom 1",
        radiator_type="single_panel",
        panels=1,
        fin_rows=0,
        height_mm=500,
        width_mm=600,
    )
    gemini = FakeGemini([_video_reading([r1, r2])])
    result = extract_radiator_video(gemini, _synthetic_mp4(), "video/mp4")

    assert result.status == "verified" and result.attempts == 1
    assert result.radiator_count == 2 and result.photo_requests == []
    (call,) = gemini.calls
    assert (call.model, call.thinking_level) == ("gemini-4-argon", "high")
    assert call.media_types == ["video"]

    rooms = apply_radiator_spec_checks(result.radiators, design_load_kw=4.5)
    assert [r.name for r in rooms] == ["Living room", "Bedroom 1"]
    assert result.radiators[0].upsize_status == "ok"
    assert result.radiators[1].upsize_status == "upsize"
    assert result.radiators[1].required_output_dt50_w > result.radiators[1].output_at_flow_temp_w


def test_count_and_dedup_failures_trigger_reask_then_pass() -> None:
    # First read double-counts the hall radiator (overlapping timestamps & identical room/size)
    # and reports radiator_count=3 for 2 entries.
    dup_a = _rad(first_seen="0:04", last_seen="0:08", room="Hall", width_mm=1000, height_mm=600)
    dup_b = _rad(first_seen="0:06", last_seen="0:09", room="Hall", width_mm=1010, height_mm=600)
    first = _video_reading([dup_a, dup_b], radiator_count=3)

    clean_a = _rad(first_seen="0:04", last_seen="0:08", room="Hall", width_mm=1000, height_mm=600)
    clean_b = _rad(
        first_seen="0:19",
        last_seen="0:23",
        room="Kitchen",
        radiator_type="K1",
        panels=1,
        fin_rows=1,
        width_mm=800,
        height_mm=600,
    )
    second = _video_reading([clean_a, clean_b], radiator_count=2)

    gemini = FakeGemini([first, second])
    result = extract_radiator_video(gemini, _synthetic_mp4(), "video/mp4")

    assert result.status == "verified" and result.attempts == 2
    assert len(result.radiators) == 2 and result.radiator_count == 2
    assert len(gemini.calls) == 2
    reask = gemini.calls[1]
    assert (reask.model, reask.thinking_level) == ("gemini-4-argon", "high")
    assert "radiator count matches list" in reask.prompt
    assert "de-duplication sanity" in reask.prompt
    assert [e.step for e in result.log].count("reread") == 1
    assert result.log[-1].step == "pass" and result.log[-1].passed


def test_failed_size_check_reasks_and_passes() -> None:
    bad = _rad(first_seen="0:05", last_seen="0:09", room="Study", width_mm=120, height_mm=600)
    fixed = _rad(first_seen="0:05", last_seen="0:09", room="Study", width_mm=900, height_mm=600)
    gemini = FakeGemini([_video_reading([bad]), _video_reading([fixed])])

    result = extract_radiator_video(gemini, _synthetic_mp4(), "video/mp4")

    assert result.status == "verified" and result.attempts == 2
    assert result.radiators[0].width_mm == 900
    assert "radiator #1 (@0:05): size plausible" in gemini.calls[1].prompt


def test_still_uncertain_radiator_becomes_photo_request_never_a_guess() -> None:
    clear = _rad(
        first_seen="0:03",
        last_seen="0:07",
        room="Living room",
        radiator_type="K2",
        panels=2,
        fin_rows=2,
        width_mm=1200,
        height_mm=600,
    )
    uncertain = _rad(
        first_seen="0:14",
        last_seen="0:17",
        room="Bedroom 2",
        radiator_type="K1",
        panels=1,
        fin_rows=1,
        width_mm=900,
        height_mm=600,
        confidence="low",
        could_not_judge=["partly hidden behind sofa; could not see top grille"],
    )
    reply = _video_reading([clear, uncertain])
    gemini = FakeGemini([reply, reply])

    result = extract_radiator_video(gemini, _synthetic_mp4(), "video/mp4")

    assert result.status == "verified_with_warnings"
    assert result.attempts == 2
    assert len(result.radiators) == 2

    first_rad, second_rad = result.radiators
    assert first_rad.status == "verified" and first_rad.photo_request is None
    assert second_rad.status == "couldnt_tell"
    assert second_rad.upsize_status == "couldnt_tell"
    # Guessed dimensions/types are cleared so they are never shown or fed into the maths.
    assert second_rad.radiator_type is None
    assert second_rad.width_mm is None and second_rad.height_mm is None
    assert second_rad.panels is None and second_rad.fin_rows is None
    assert second_rad.photo_request == "couldn't tell: photograph the radiator seen at 0:14"
    assert result.photo_requests == ["couldn't tell: photograph the radiator seen at 0:14"]

    # Spec check only rates verified radiators; uncertain ones are never guessed.
    rooms = apply_radiator_spec_checks(result.radiators, design_load_kw=5.0)
    assert [r.name for r in rooms] == ["Living room"]
    assert second_rad.upsize_status == "couldnt_tell"


# --- HTTP route: POST /api/radiators/video ---------------------------------------------------


@pytest.fixture
def video_api(lookup):
    fake = FakeGemini()
    app.dependency_overrides[get_gemini] = lambda: fake
    app.dependency_overrides[get_datasheets] = lambda: lookup
    yield fake
    app.dependency_overrides.clear()


client = TestClient(app)


def test_radiators_video_route_returns_spec_checks_and_photo_requests(video_api) -> None:
    r1 = _rad(first_seen="0:02", last_seen="0:06", room="Lounge", width_mm=2000, height_mm=600)
    r2 = _rad(
        first_seen="0:14",
        last_seen="0:16",
        room="Box room",
        confidence="low",
        could_not_judge=["motion blur on top grille"],
    )
    reply = _video_reading([r1, r2])
    video_api.replies.extend([reply, reply])

    response = client.post(
        "/api/radiators/video",
        data={"design_load_kw": "4.5"},
        files={"file": ("walkthrough.mp4", _synthetic_mp4(), "video/mp4")},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "verified_with_warnings"
    assert body["radiators"][0]["upsize_status"] == "ok"
    assert body["radiators"][1]["upsize_status"] == "couldnt_tell"
    assert body["photo_requests"] == ["couldn't tell: photograph the radiator seen at 0:14"]


def test_radiators_video_route_rejects_bad_mime_and_overlong_clip(video_api) -> None:
    bad_mime = client.post(
        "/api/radiators/video",
        files={"file": ("clip.txt", b"hello", "text/plain")},
    )
    assert bad_mime.status_code == 415

    overlong = _synthetic_mp4(duration_ms=95_000)
    resp = client.post(
        "/api/radiators/video",
        files={"file": ("long.mp4", overlong, "video/mp4")},
    )
    assert resp.status_code == 422
    assert "maximum length is 90 seconds" in resp.text
