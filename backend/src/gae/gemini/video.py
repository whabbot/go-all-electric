"""Radiator walk-through video reader: privacy scrubbing, Argon-high extraction, and checks.

Homeowners can film a quick walk past their radiators instead of photographing each one.
Before anything leaves the server:
1. Size (<= 100 MB) and duration (<= 90 s) caps are enforced.
2. Container metadata (GPS/location atoms like `©xyz` and `loci`, `udta`, `meta`, `uuid`,
   `XMP_`, device make/model tags, creation/modification timestamps in `mvhd`/`tkhd`/`mdhd`,
   and handler names in `hdlr`) is scrubbed in memory. If an uncommon container requires
   remuxing, `ffmpeg` runs inside a private temp directory that is deleted in a `finally`.

Then Gemini 4 Argon (`thinking_level="high"`, `store=False`) counts distinct radiators and
estimates each one's timestamp, room, type, panels/fins, and size. Deterministic code checks
validate the count, de-duplication, size plausibility, panel/fin consistency, and confidence.
Any failed check triggers one re-read on Argon-high with the failed checks spelled out; any
radiator still uncertain after the re-read becomes a `"couldn't tell: photograph the radiator
seen at 0:14"` request rather than a guess.
"""

from __future__ import annotations

import contextlib
import json
import re
import shutil
import struct
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from gae.gemini import checks
from gae.gemini.client import StructuredModel, text, video
from gae.gemini.extract import SYSTEM
from gae.gemini.schemas import (
    RadiatorVideoReading,
    RadiatorVideoResult,
    VerificationLog,
    VerifiedVideoRadiator,
    VideoRadiator,
)
from gae.heatpump import constants as c
from gae.heatpump.spec import Room
from gae.heatpump.spec import check_radiator as spec_check_radiator

MAX_VIDEO_BYTES = 100 * 1024 * 1024  # 100 MB
MAX_VIDEO_DURATION_S = 90.0  # 90 seconds
ALLOWED_VIDEO_MIMES = {"video/mp4", "video/quicktime", "video/webm"}
VIDEO_KIND = "radiator_video"

# Fallback whole-house design heat loss when checking a video outside a full house analysis.
DEFAULT_STANDALONE_DESIGN_LOAD_KW = 3.5

VIDEO_PROMPT = (
    "This is a homeowner's walk-through video of the radiators in their home. "
    "Watch the whole clip, count the distinct radiators (`radiator_count`), and list each "
    "distinct radiator once in order of first appearance (`radiators`). If the camera pans "
    "past the same radiator more than once, merge those views into one entry.\n\n"
    "For each radiator report:\n"
    "- `first_seen`: timestamp when it first appears in M:SS format (e.g. '0:04', '0:14').\n"
    "- `last_seen`: timestamp when the view of that radiator ends in M:SS format, or null.\n"
    "- `room`: room name if inferable from context or labels, otherwise null.\n"
    "- `radiator_type`: 'single_panel', 'K1', 'P+', 'K2', 'K3', 'column', 'towel_rail', or "
    "'other', based on steel panels and convector fin rows (K1 = 1 panel + 1 fin row, "
    "P+ = 2 panels + 1, K2 = 2 + 2, K3 = 3 + 3).\n"
    "- `panels` and `fin_rows`: integer counts matching the type.\n"
    "- `width_mm` and `height_mm`: estimated width and height in mm using nearby objects "
    "(skirting boards, sockets, doors, bricks, or visible labels) for scale.\n"
    "- `legible`: false if the radiator is too blurry, dark, brief, or occluded to judge.\n"
    "- `confidence`: 'high', 'medium', or 'low'.\n"
    "- `could_not_judge`: list any details you could not judge (e.g. 'fin rows hidden by cover'), "
    "or [] when clear. Never guess a size or type when uncertain."
)

# ISO BMFF container boxes whose children we walk recursively.
_CONTAINER_BOXES = {
    b"moov",
    b"trak",
    b"mdia",
    b"minf",
    b"dinf",
    b"stbl",
    b"edts",
    b"moof",
    b"traf",
    b"mvex",
}

# ISO BMFF metadata boxes that may carry GPS/location, device make/model, user data, or XMP.
# These are overwritten in-place with zero-filled `free` boxes of identical length.
_METADATA_BOXES = {
    b"udta",
    b"meta",
    b"uuid",
    b"XMP_",
    b"loci",
    b"ilst",
    b"keys",
    b"ID32",
    b"tagc",
    b"gps ",
}

_TOP_LEVEL_ISOBMFF = {
    b"ftyp",
    b"moov",
    b"mdat",
    b"free",
    b"skip",
    b"wide",
    b"styp",
    b"pdin",
    b"moof",
    b"mfra",
} | _METADATA_BOXES


def _normalize_mime(mime_type: str) -> str:
    base = (mime_type or "").split(";", 1)[0].strip().lower()
    if base in ("video/x-m4v", "video/mp4v-es"):
        return "video/mp4"
    if base == "video/mov":
        return "video/quicktime"
    return base


def _looks_like_isobmff(data: bytes) -> bool:
    if len(data) < 8:
        return False
    box_type = data[4:8]
    return box_type in _TOP_LEVEL_ISOBMFF or (box_type and box_type[0] == 0xA9)


def _scrub_isobmff_in_memory(data: bytes) -> tuple[bytes, float | None]:
    """Strip location, device, and timestamp metadata in-place from an MP4/MOV buffer."""
    buf = bytearray(data)
    durations: list[float] = []

    def walk(start: int, end: int) -> None:
        pos = start
        while pos + 8 <= end:
            size = struct.unpack(">I", buf[pos : pos + 4])[0]
            box_type = bytes(buf[pos + 4 : pos + 8])
            header_len = 8
            if size == 1:
                if pos + 16 > end:
                    break
                size = struct.unpack(">Q", buf[pos + 8 : pos + 16])[0]
                header_len = 16
            elif size == 0:
                size = end - pos
            if size < header_len or pos + size > end:
                break
            box_end = pos + size
            body = pos + header_len

            if box_type in _METADATA_BOXES or (box_type and box_type[0] == 0xA9):
                buf[pos + 4 : pos + 8] = b"free"
                buf[body:box_end] = b"\x00" * (box_end - body)
            elif box_type in (b"mvhd", b"tkhd", b"mdhd"):
                if body + 4 <= box_end:
                    version = buf[body]
                    if version == 0 and body + 12 <= box_end:
                        # Zero creation_time (4B) and modification_time (4B).
                        buf[body + 4 : body + 12] = b"\x00" * 8
                        if box_type in (b"mvhd", b"mdhd") and body + 20 <= box_end:
                            timescale, duration = struct.unpack(">II", buf[body + 12 : body + 20])
                            if timescale > 0 and duration > 0 and duration != 0xFFFFFFFF:
                                durations.append(duration / timescale)
                    elif version == 1 and body + 20 <= box_end:
                        # Zero creation_time (8B) and modification_time (8B).
                        buf[body + 4 : body + 20] = b"\x00" * 16
                        if box_type in (b"mvhd", b"mdhd") and body + 32 <= box_end:
                            timescale = struct.unpack(">I", buf[body + 20 : body + 24])[0]
                            duration = struct.unpack(">Q", buf[body + 24 : body + 32])[0]
                            if timescale > 0 and duration > 0 and duration != 0xFFFFFFFFFFFFFFFF:
                                durations.append(duration / timescale)
            elif box_type == b"hdlr":
                # FullBox (4B) + pre_defined (4B) + handler_type (4B) + reserved (12B) = 24B,
                # followed by the human-readable handler/software name.
                if body + 24 < box_end:
                    buf[body + 24 : box_end] = b"\x00" * (box_end - (body + 24))
            elif box_type in _CONTAINER_BOXES:
                walk(body, box_end)

            pos = box_end

    walk(0, len(buf))
    duration_s = max(durations) if durations else None
    return bytes(buf), duration_s


def _remux_with_private_tempdir(data: bytes, mime_type: str) -> tuple[bytes, float | None]:
    """Fallback remuxer using a private temporary directory cleaned up in `finally`."""
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg:
        raise ValueError("Unsupported video container; upload an MP4 or MOV clip.")
    ext = {"video/mp4": ".mp4", "video/quicktime": ".mov", "video/webm": ".webm"}.get(
        mime_type, ".mp4"
    )
    with tempfile.TemporaryDirectory(prefix="gae-video-") as tmp_dir:
        tmp_path = Path(tmp_dir)
        in_file = tmp_path / f"in{ext}"
        out_file = tmp_path / f"out{ext}"
        try:
            in_file.write_bytes(data)
            duration_s: float | None = None
            if ffprobe:
                probe = subprocess.run(
                    [
                        ffprobe,
                        "-v",
                        "error",
                        "-show_entries",
                        "format=duration",
                        "-of",
                        "default=noprint_wrappers=1:nokey=1",
                        str(in_file),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=15,
                    check=False,
                )
                try:
                    val = float(probe.stdout.strip())
                    if val > 0:
                        duration_s = val
                except ValueError:
                    pass
            cmd = [
                ffmpeg,
                "-y",
                "-v",
                "error",
                "-i",
                str(in_file),
                "-map_metadata",
                "-1",
                "-c",
                "copy",
            ]
            if ext in (".mp4", ".mov"):
                cmd.extend(["-movflags", "+faststart"])
            cmd.append(str(out_file))
            proc = subprocess.run(cmd, capture_output=True, timeout=30, check=False)
            if proc.returncode != 0 or not out_file.exists():
                raise ValueError("Could not read or sanitize video clip; upload a standard MP4.")
            return out_file.read_bytes(), duration_s
        finally:
            for p in (in_file, out_file):
                with contextlib.suppress(OSError):
                    p.unlink(missing_ok=True)


def sanitize_video(data: bytes, mime_type: str) -> tuple[bytes, str, float | None]:
    """Validate size and length caps and strip container metadata before calling Gemini."""
    norm_mime = _normalize_mime(mime_type)
    if norm_mime not in ALLOWED_VIDEO_MIMES:
        raise ValueError("Upload an MP4, MOV or WebM video clip")
    if not data:
        raise ValueError("Video is empty")
    if len(data) > MAX_VIDEO_BYTES:
        mb = len(data) / (1024 * 1024)
        raise ValueError(
            f"Video exceeds the 100 MB limit ({mb:.1f} MB). "
            "Film a shorter clip or lower the camera resolution."
        )

    if norm_mime in ("video/mp4", "video/quicktime") and _looks_like_isobmff(data):
        cleaned, duration_s = _scrub_isobmff_in_memory(data)
    else:
        cleaned, duration_s = _remux_with_private_tempdir(data, norm_mime)

    if duration_s is not None and duration_s > MAX_VIDEO_DURATION_S:
        limit_s = int(MAX_VIDEO_DURATION_S)
        raise ValueError(f"Video is {duration_s:.0f}s long; maximum length is {limit_s} seconds.")
    return cleaned, norm_mime, duration_s


_TS_RE = re.compile(r"^\s*(?:(\d+):)?(\d{1,2}):(\d{2})\s*$")
_SEC_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*s?\s*$")


def parse_timestamp(raw: str | None) -> tuple[str, int | None]:
    """Normalize a timestamp into `M:SS` and return `(normalized_str, total_seconds)`."""
    if not raw or not raw.strip():
        return "0:00", None
    text_val = raw.strip()
    m = _TS_RE.match(text_val)
    if m:
        hours = int(m.group(1) or 0)
        minutes = int(m.group(2))
        seconds = int(m.group(3))
        if seconds >= 60:
            return text_val, None
        total = hours * 3600 + minutes * 60 + seconds
        return f"{total // 60}:{total % 60:02d}", total
    m_sec = _SEC_RE.match(text_val)
    if m_sec:
        total = round(float(m_sec.group(1)))
        return f"{total // 60}:{total % 60:02d}", total
    return text_val, None


@dataclass(frozen=True)
class VideoCheckOutcome:
    clip_checks: list[checks.Check]
    radiator_checks: list[list[checks.Check]]
    duplicate_indices: set[int]

    @property
    def all_checks(self) -> list[checks.Check]:
        out = list(self.clip_checks)
        for group in self.radiator_checks:
            out.extend(group)
        return out


def _find_duplicates(radiators: list[VideoRadiator]) -> tuple[list[str], set[int]]:
    """Detect duplicate radiator entries by overlapping timestamp range or same room + size."""
    reasons: list[str] = []
    dup_indices: set[int] = set()
    parsed = []
    for rad in radiators:
        first_str, start_s = parse_timestamp(rad.first_seen)
        _, end_s = parse_timestamp(rad.last_seen) if rad.last_seen else (first_str, start_s)
        if start_s is not None and (end_s is None or end_s < start_s):
            end_s = start_s
        parsed.append((first_str, start_s, end_s))

    for i in range(len(radiators)):
        for j in range(i + 1, len(radiators)):
            r1, r2 = radiators[i], radiators[j]
            ts1, s1, e1 = parsed[i]
            ts2, s2, e2 = parsed[j]
            if s1 is not None and s2 is not None and e1 is not None and e2 is not None:
                overlaps = max(s1, s2) <= min(e1, e2) or abs(s1 - s2) <= 1
                if overlaps:
                    reasons.append(
                        f"radiator #{i + 1} (@{ts1}) and radiator #{j + 1} (@{ts2}) "
                        "share the same timestamp range"
                    )
                    dup_indices.add(j)
                    continue
            room1 = (r1.room or "").strip().lower()
            room2 = (r2.room or "").strip().lower()
            if (
                room1
                and room1 == room2
                and r1.radiator_type == r2.radiator_type
                and r1.width_mm is not None
                and r2.width_mm is not None
                and r1.height_mm is not None
                and r2.height_mm is not None
                and abs(r1.width_mm - r2.width_mm) <= 100
                and abs(r1.height_mm - r2.height_mm) <= 100
            ):
                reasons.append(
                    f"radiator #{i + 1} (@{ts1}) and radiator #{j + 1} (@{ts2}) "
                    f"have near-identical size in the same room ({r1.room})"
                )
                dup_indices.add(j)
    return reasons, dup_indices


def check_radiator_video(
    reading: RadiatorVideoReading, duration_s: float | None = None
) -> VideoCheckOutcome:
    """Run clip-level count/de-dup checks and per-radiator checks."""
    clip_checks: list[checks.Check] = [
        checks.Check(
            "video legible",
            reading.legible and len(reading.radiators) > 0,
            f"{len(reading.radiators)} radiator(s) read"
            if reading.legible and reading.radiators
            else "no legible radiators read from clip",
        ),
        checks.Check(
            "radiator count matches list",
            reading.radiator_count == len(reading.radiators) and reading.radiator_count >= 1,
            f"reported count {reading.radiator_count} vs {len(reading.radiators)} listed",
        ),
    ]
    dup_reasons, dup_indices = _find_duplicates(reading.radiators)
    clip_checks.append(
        checks.Check(
            "de-duplication sanity",
            len(dup_reasons) == 0,
            "; ".join(dup_reasons)
            if dup_reasons
            else f"{len(reading.radiators)} distinct radiator(s)",
        )
    )

    radiator_checks: list[list[checks.Check]] = []
    for idx, rad in enumerate(reading.radiators, start=1):
        norm_ts, start_s = parse_timestamp(rad.first_seen)
        prefix = f"radiator #{idx} (@{norm_ts})"
        base_outcome = checks.check_radiator(rad)
        rad_list: list[checks.Check] = [
            checks.Check(
                f"{prefix}: {chk.name}",
                chk.passed,
                chk.detail,
                hard=chk.hard,
            )
            for chk in base_outcome.checks
        ]
        ts_ok = start_s is not None and (duration_s is None or start_s <= duration_s + 1.0)
        rad_list.append(
            checks.Check(
                f"{prefix}: timestamp valid",
                ts_ok,
                norm_ts if ts_ok else f"timestamp {rad.first_seen!r} outside clip",
            )
        )
        confident = rad.confidence in ("high", "medium") and not rad.could_not_judge
        conf_detail = f"confidence={rad.confidence}"
        if rad.could_not_judge:
            conf_detail += f", could not judge: {', '.join(rad.could_not_judge)}"
        rad_list.append(
            checks.Check(
                f"{prefix}: confidence sufficient",
                confident,
                conf_detail,
            )
        )
        radiator_checks.append(rad_list)

    return VideoCheckOutcome(
        clip_checks=clip_checks,
        radiator_checks=radiator_checks,
        duplicate_indices=dup_indices,
    )


def _reread_video_prompt(reading: RadiatorVideoReading, failed: list[checks.Check]) -> str:
    problems = "\n".join(f"- {c.name}: {c.detail}" for c in failed)
    return (
        f"{VIDEO_PROMPT}\n\nA previous reading of this same walkthrough video was:\n"
        f"{reading.model_dump_json()}\n\nCode checks on that reading failed:\n{problems}\n\n"
        "Watch the video again carefully at those timestamps:\n"
        "1. If the same physical radiator was listed twice, merge it into one entry and update "
        "`radiator_count` to match the length of `radiators`.\n"
        "2. Re-check the panels, convector fin rows, width, and height of every flagged radiator.\n"
        "3. If a radiator at a timestamp is genuinely blurry, occluded, or too dark to judge "
        "reliably, set its `legible` to false or `confidence` to 'low' and explain why in "
        "`could_not_judge` rather than guessing."
    )


def _summarise_video_reading(reading: RadiatorVideoReading) -> str:
    items = []
    for rad in reading.radiators:
        norm_ts, _ = parse_timestamp(rad.first_seen)
        items.append(
            {
                "at": norm_ts,
                "room": rad.room,
                "type": rad.radiator_type,
                "size": f"{rad.height_mm}x{rad.width_mm}",
                "conf": rad.confidence,
            }
        )
    summary = {"radiator_count": reading.radiator_count, "radiators": items}
    return json.dumps(summary, separators=(", ", ": "))[:300]


def core_radiator_type(kind: str | None) -> str:
    return {
        "single_panel": "single",
        "K1": "K1",
        "P+": "P+",
        "K2": "K2",
        "K3": "K3",
        "column": "column",
        "towel_rail": "single",
    }.get(kind or "", "K1")


def apply_radiator_spec_checks(
    radiators: list[VerifiedVideoRadiator],
    *,
    design_load_kw: float | None = None,
    flow_temp_c: float = c.TARGET_FLOW_TEMP_C,
) -> list[Room]:
    """Populate upsize fields on each verified radiator and return `Room` items."""
    rateable = [
        r
        for r in radiators
        if r.status != "couldnt_tell"
        and r.radiator_type in c.PANEL_RADIATOR_DT50_W_PER_M2
        and r.width_mm is not None
        and r.height_mm is not None
    ]
    if not rateable:
        return []
    load_kw = (
        design_load_kw
        if design_load_kw is not None and design_load_kw > 0
        else DEFAULT_STANDALONE_DESIGN_LOAD_KW
    )
    share = min(c.PHOTOGRAPHED_ROOM_SHARE_OF_HEAT_LOSS, 1.0 / len(rateable))
    loss_w = load_kw * 1000.0 * share
    rooms: list[Room] = []
    for idx, rad in enumerate(rateable, start=1):
        per_m2 = c.PANEL_RADIATOR_DT50_W_PER_M2[rad.radiator_type]
        rated_dt50_w = per_m2 * (rad.height_mm or 600) * (rad.width_mm or 1000) / 1e6
        room_name = rad.room or f"Radiator {idx} ({rad.first_seen})"
        room = Room(name=room_name, heat_loss_w=loss_w, radiator_output_dt50_w=rated_dt50_w)
        emitter = spec_check_radiator(room, flow_temp_c)
        rad.upsize_status = emitter.status.value
        rad.output_at_flow_temp_w = round(emitter.output_w, 1)
        rad.heat_loss_w = round(emitter.heat_loss_w, 1)
        rad.required_output_dt50_w = round(emitter.required_output_dt50_w, 1)
        rad.min_flow_temp_c = round(emitter.min_flow_temp_c, 1)
        rooms.append(room)
    return rooms


def extract_radiator_video(
    gemini: StructuredModel,
    data: bytes,
    mime_type: str = "video/mp4",
    *,
    design_load_kw: float | None = None,
    flow_temp_c: float = c.TARGET_FLOW_TEMP_C,
    log: VerificationLog | None = None,
) -> RadiatorVideoResult:
    """Sanitize video, read with Gemini 4 Argon (high thinking), verify, and re-ask on failure."""
    clean_bytes, norm_mime, duration_s = sanitize_video(data, mime_type)
    video_block = video(clean_bytes, norm_mime)
    log = VerificationLog() if log is None else log
    model = gemini.lead_model

    reading: RadiatorVideoReading | None = None
    outcome: VideoCheckOutcome | None = None
    failed: list[checks.Check] = []

    for attempt in (1, 2):
        first = attempt == 1
        prompt = VIDEO_PROMPT if first else _reread_video_prompt(reading, failed)
        reading = gemini.generate(
            model=model,
            input=[text(prompt), video_block],
            schema=RadiatorVideoReading,
            thinking_level="high",
            system_instruction=SYSTEM,
            timeout_s=120.0,
        )
        log.add(
            "read" if first else "reread",
            VIDEO_KIND,
            model,
            "Gemini reads the radiator walkthrough video"
            if first
            else "Gemini re-reads the video with the failed checks",
            True,
            _summarise_video_reading(reading),
        )
        outcome = check_radiator_video(reading, duration_s=duration_s)
        failed = [chk for chk in outcome.all_checks if not chk.passed]

        for chk in outcome.clip_checks:
            if chk.passed:
                action = "ok"
            elif first:
                action = "ask Gemini to look again"
            else:
                action = "couldn't tell" if chk.hard else "keep reading, show as a warning"
            log.add("check", VIDEO_KIND, "code", f"{chk.name}: {chk.detail}", chk.passed, action)

        for idx, rad_checks in enumerate(outcome.radiator_checks):
            norm_ts, _ = parse_timestamp(reading.radiators[idx].first_seen)
            for chk in rad_checks:
                if chk.passed:
                    action = "ok"
                elif first:
                    action = "ask Gemini to look again"
                elif chk.hard:
                    action = f"couldn't tell: photograph the radiator seen at {norm_ts}"
                else:
                    action = "keep reading, show as a warning"
                log.add(
                    "check", VIDEO_KIND, "code", f"{chk.name}: {chk.detail}", chk.passed, action
                )

        if not failed:
            log.add("pass", VIDEO_KIND, "code", "all checks passed", True, "use this reading")
            verified_rads = [_build_verified_radiator(rad, []) for rad in reading.radiators]
            apply_radiator_spec_checks(
                verified_rads, design_load_kw=design_load_kw, flow_temp_c=flow_temp_c
            )
            return RadiatorVideoResult(
                status="verified",
                attempts=attempt,
                model=model,
                radiator_count=len(verified_rads),
                radiators=verified_rads,
                photo_requests=[],
                could_not_judge=list(reading.could_not_judge),
                warnings=[],
                log=log.entries,
            )

    assert reading is not None and outcome is not None
    clip_warnings = [f"{chk.name}: {chk.detail}" for chk in outcome.clip_checks if not chk.passed]
    verified_rads: list[VerifiedVideoRadiator] = []
    photo_requests: list[str] = []

    for idx, (rad, rad_checks) in enumerate(
        zip(reading.radiators, outcome.radiator_checks, strict=True)
    ):
        if idx in outcome.duplicate_indices:
            continue
        norm_ts, _ = parse_timestamp(rad.first_seen)
        norm_last, _ = parse_timestamp(rad.last_seen) if rad.last_seen else (None, None)
        rad_failed = [chk for chk in rad_checks if not chk.passed]
        rad_hard = [chk for chk in rad_failed if chk.hard]
        if rad_hard:
            req = f"couldn't tell: photograph the radiator seen at {norm_ts}"
            photo_requests.append(req)
            log.add(
                "fail",
                VIDEO_KIND,
                "code",
                "; ".join(chk.name for chk in rad_hard),
                False,
                req,
            )
            verified_rads.append(
                VerifiedVideoRadiator(
                    first_seen=norm_ts,
                    last_seen=norm_last,
                    room=rad.room,
                    status="couldnt_tell",
                    radiator_type=None,
                    panels=None,
                    fin_rows=None,
                    width_mm=None,
                    height_mm=None,
                    confidence="low",
                    could_not_judge=list(rad.could_not_judge),
                    warnings=[f"{chk.name}: {chk.detail}" for chk in rad_failed],
                    photo_request=req,
                    upsize_status="couldnt_tell",
                )
            )
        else:
            soft_warnings = [f"{chk.name}: {chk.detail}" for chk in rad_failed]
            verified_rads.append(_build_verified_radiator(rad, soft_warnings))

    apply_radiator_spec_checks(
        verified_rads, design_load_kw=design_load_kw, flow_temp_c=flow_temp_c
    )

    any_verified = any(r.status in ("verified", "verified_with_warnings") for r in verified_rads)
    if not any_verified:
        if not photo_requests:
            fallback_req = (
                "couldn't tell: photograph each radiator from the front with a tape measure "
                "across it, plus one shot looking down between the panels"
            )
            photo_requests.append(fallback_req)
            log.add(
                "fail",
                VIDEO_KIND,
                "code",
                "; ".join(chk.name for chk in outcome.clip_checks if not chk.passed)
                or "video illegible",
                False,
                fallback_req,
            )
        return RadiatorVideoResult(
            status="couldnt_tell",
            attempts=2,
            model=model,
            radiator_count=len(verified_rads),
            radiators=verified_rads,
            photo_requests=photo_requests,
            could_not_judge=list(reading.could_not_judge),
            warnings=clip_warnings,
            log=log.entries,
        )

    all_clean = (
        not clip_warnings
        and not photo_requests
        and all(r.status == "verified" for r in verified_rads)
    )
    overall_status = "verified" if all_clean else "verified_with_warnings"
    log.add(
        "pass",
        VIDEO_KIND,
        "code",
        "verified radiators kept; uncertain ones requested as photos"
        if photo_requests
        else "hard checks passed",
        True,
        "use verified radiators and request photos for uncertain ones"
        if photo_requests
        else "use this reading with warnings",
    )
    return RadiatorVideoResult(
        status=overall_status,
        attempts=2,
        model=model,
        radiator_count=len(verified_rads),
        radiators=verified_rads,
        photo_requests=photo_requests,
        could_not_judge=list(reading.could_not_judge),
        warnings=clip_warnings,
        log=log.entries,
    )


def _build_verified_radiator(rad: VideoRadiator, warnings: list[str]) -> VerifiedVideoRadiator:
    norm_ts, _ = parse_timestamp(rad.first_seen)
    norm_last, _ = parse_timestamp(rad.last_seen) if rad.last_seen else (None, None)
    return VerifiedVideoRadiator(
        first_seen=norm_ts,
        last_seen=norm_last,
        room=rad.room,
        status="verified_with_warnings" if warnings else "verified",
        radiator_type=rad.radiator_type,
        panels=rad.panels,
        fin_rows=rad.fin_rows,
        width_mm=rad.width_mm,
        height_mm=rad.height_mm,
        confidence=rad.confidence,
        could_not_judge=list(rad.could_not_judge),
        warnings=warnings,
        photo_request=None,
    )
