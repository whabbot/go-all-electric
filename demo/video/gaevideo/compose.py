"""ffmpeg assembly: one clip per beat (footage minus cut waits, captions, narration), joined."""

import subprocess
from pathlib import Path

from gaevideo import graphics as gfx
from gaevideo.record import LEAD, BeatMarks
from gaevideo.storyboard import (
    caption_chunks,
    caption_times,
    cut_positions,
    frame_list,
    kept_intervals,
)

FPS = 30
LIVE_LABEL = (110, 210, 150)  # corner label over inserted real footage
ENC = [
    "-c:v",
    "libx264",
    "-preset",
    "medium",
    "-crf",
    "19",
    "-pix_fmt",
    "yuv420p",
    "-r",
    str(FPS),
    "-c:a",
    "aac",
    "-b:a",
    "160k",
    "-ar",
    "48000",
    "-ac",
    "2",
]


def _run(cmd: list[str]) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", *cmd], check=True)


def _concat_list(items: list[tuple[str, float]], path: Path) -> Path:
    lines = ["ffconcat version 1.0"]
    for img, secs in items:
        lines += [f"file '{img}'", f"duration {secs:.4f}"]
    lines.append(f"file '{items[-1][0]}'")  # the demuxer ignores the last entry's duration
    path.write_text("\n".join(lines) + "\n")
    return path


def beat_clip(
    index: int,
    beat_id: str,
    narration: str,
    mark: BeatMarks,
    frames: list[tuple[float, str]],
    voice: tuple[Path, float],
    work: Path,
    badge: list[str] | None,
    insert: Path | None,
    labels: list[tuple[str, float, float]] | None = None,
) -> tuple[Path, float, list[tuple[float, float, str]]]:
    """Render one beat. Returns the clip, its length and its captions (beat clock).

    `labels` (text, from, to) replace the badge, e.g. over an inserted clip of real footage."""
    wav, narr_s = voice
    intervals = kept_intervals(mark.start, mark.end, [(a, b) for a, b, _ in mark.cuts])
    length = sum(b - a for a, b in intervals)
    stem = work / f"{index:02d}-{beat_id}"

    inputs: list[str] = []
    if insert is not None:
        length = max(length, probe_duration(insert))  # the whole clip plays; narration then rests
        inputs += ["-i", str(insert)]
        base = (
            f"[0:v]fps={FPS},scale={gfx.APP_W}:{gfx.APP_H}:force_original_aspect_ratio=decrease,"
            f"pad={gfx.W}:{gfx.H}:(ow-iw)/2:({gfx.APP_H}-ih)/2:color=0x111111,setsar=1,"
            f"tpad=stop_mode=clone:stop_duration={length:.3f},trim=duration={length:.3f}[v0]"
        )
    else:
        inputs += [
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(_concat_list(frame_list(frames, intervals), stem.with_suffix(".txt"))),
        ]
        base = (
            f"[0:v]fps={FPS},scale={gfx.APP_W}:{gfx.APP_H}:flags=lanczos,"
            f"pad={gfx.W}:{gfx.H}:{gfx.APP_X}:0:color=0x111111,setsar=1[v0]"
        )

    chain, label, n = [base], "v0", 1
    caps = caption_times(caption_chunks(narration), LEAD, narr_s)
    for k, (a, b, text) in enumerate(caps):
        inputs += ["-i", str(gfx.caption(text, stem.with_name(f"{stem.name}-cap{k}.png")))]
        chain.append(
            f"[{label}][{n}:v]overlay=0:{gfx.APP_H}:enable='between(t,{a:.3f},{b:.3f})'[v{n}]"
        )
        label, n = f"v{n}", n + 1
    for k, ((pos, removed), (_, _, what)) in enumerate(
        zip(
            cut_positions(mark.start, [(a, b) for a, b, _ in mark.cuts]),
            sorted(mark.cuts),
            strict=True,
        )
    ):
        text = f"Shortened: {_human(removed)} of waiting for the {what} cut"
        inputs += ["-i", str(gfx.banner(text, stem.with_name(f"{stem.name}-cut{k}.png")))]
        chain.append(
            f"[{label}][{n}:v]overlay={gfx.APP_X}+({gfx.APP_W}-w)/2:96:"
            f"enable='between(t,{max(0, pos - 0.1):.3f},{pos + 3.2:.3f})'[v{n}]"
        )
        label, n = f"v{n}", n + 1
    if labels is not None:
        for k, (text, a, b) in enumerate(labels):
            png = gfx.side_label([text], stem.with_name(f"{stem.name}-label{k}.png"), LIVE_LABEL)
            inputs += ["-i", str(png)]
            chain.append(f"[{label}][{n}:v]overlay=0:0:enable='between(t,{a:.3f},{b:.3f})'[v{n}]")
            label, n = f"v{n}", n + 1
    elif badge:
        inputs += ["-i", str(gfx.side_label(badge, stem.with_name(f"{stem.name}-badge.png")))]
        chain.append(f"[{label}][{n}:v]overlay=0:0[v{n}]")
        label, n = f"v{n}", n + 1
    inputs += ["-i", str(wav)]
    delay = int(LEAD * 1000)
    chain.append(
        f"[{n}:a]adelay={delay}|{delay},apad,atrim=duration={length:.3f},"
        f"aformat=sample_rates=48000:channel_layouts=stereo[a]"
    )

    clip = stem.with_suffix(".mp4")
    _run(
        [
            *inputs,
            "-filter_complex",
            ";".join(chain),
            "-map",
            f"[{label}]",
            "-map",
            "[a]",
            "-t",
            f"{length:.3f}",
            *ENC,
            str(clip),
        ]
    )
    return clip, length, caps


def join(clips: list[Path], out: Path) -> None:
    listing = out.with_suffix(".clips.txt")
    listing.write_text("".join(f"file '{c}'\n" for c in clips))
    _run(
        [
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(listing),
            # Video is copied; audio is re-encoded so the joins carry no timestamp gaps.
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-movflags",
            "+faststart",
            str(out),
        ]
    )
    listing.unlink()


def voiceover_track(
    voices: list[tuple[Path, float]], gap: float, out: Path
) -> list[tuple[float, float]]:
    """All narration lines in order with `gap` seconds between; returns each line's start/end."""
    times, t, parts = [], 0.0, []
    for i, (_, secs) in enumerate(voices):
        times.append((t, t + secs))
        parts.append(
            f"[{i}:a]aformat=sample_rates=48000:channel_layouts=stereo,apad=pad_dur={gap}[p{i}]"
        )
        t += secs + gap
    cmd: list[str] = []
    for wav, _ in voices:
        cmd += ["-i", str(wav)]
    graph = (
        ";".join(parts)
        + ";"
        + "".join(f"[p{i}]" for i in range(len(voices)))
        + f"concat=n={len(voices)}:v=0:a=1[a]"
    )
    _run([*cmd, "-filter_complex", graph, "-map", "[a]", str(out)])
    return times


def mux(video: Path, audio: Path, out: Path) -> None:
    """A screen recording made by hand plus the voiceover track, as a 1080p MP4."""
    _run(
        [
            "-i",
            str(video),
            "-i",
            str(audio),
            "-filter_complex",
            f"[0:v]fps={FPS},scale={gfx.W}:{gfx.H}:force_original_aspect_ratio=decrease,"
            f"pad={gfx.W}:{gfx.H}:(ow-iw)/2:(oh-ih)/2:color=0x111111,setsar=1[v]",
            "-map",
            "[v]",
            "-map",
            "1:a",
            "-shortest",
            *ENC,
            "-movflags",
            "+faststart",
            str(out),
        ]
    )


def _human(secs: float) -> str:
    secs = round(secs)
    return f"{secs} s" if secs < 60 else f"{secs // 60} min {secs % 60:02d} s"


def probe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(out.stdout.strip())
