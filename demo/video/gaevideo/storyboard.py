"""Storyboard loading and the pure timing maths (captions, cuts, frame lists)."""

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

STORIES = ("draft", "final")


@dataclass
class Beat:
    id: str
    screen: str
    narration: str
    actions: list[tuple[str, dict]]
    insert: str | None = None
    insert_label: str | None = None


@dataclass
class Storyboard:
    voice_style: str
    beats: list[Beat] = field(default_factory=list)


def load(path: Path, story: str) -> Storyboard:
    """Beats and steps for one story, with that story's narration."""
    if story not in STORIES:
        raise ValueError(f"story must be one of {STORIES}")
    raw = yaml.safe_load(path.read_text())
    beats = []
    for b in raw["beats"]:
        if b.get("only", story) != story:
            continue
        narration = " ".join(str(b.get(story) or "").split())
        if not narration:
            raise ValueError(f"beat {b['id']} has no {story} narration")
        actions = []
        for step in b.get("actions") or []:
            if not isinstance(step, dict) or len(step) != 1:
                raise ValueError(f"beat {b['id']}: each step is a one-key mapping, got {step!r}")
            ((name, args),) = step.items()
            args = dict(args or {})
            if args.pop("only", story) != story:
                continue
            actions.append((name, args))
        beats.append(
            Beat(
                b["id"],
                b.get("screen", ""),
                narration,
                actions,
                b.get("insert"),
                b.get("insert_label"),
            )
        )
    return Storyboard(" ".join(str(raw.get("voice_style", "")).split()), beats)


def caption_chunks(text: str, max_chars: int = 84) -> list[str]:
    """Split narration into one-line captions at sentence, then clause, then word breaks."""
    out: list[str] = []
    for sentence in re.split(r"(?<=[.?!])\s+", text.strip()):
        pending = [sentence]
        while pending:
            part = pending.pop(0)
            if len(part) <= max_chars:
                out.append(part)
                continue
            cut = _best_break(part, max_chars)
            pending[:0] = [part[:cut].strip(), part[cut:].strip()]
    return [c for c in out if c]


def _best_break(text: str, limit: int) -> int:
    for sep in (": ", "; ", ", ", " "):
        i = text.rfind(sep, 0, limit)
        if i > limit // 3:
            return i + len(sep)
    return limit


def caption_times(
    chunks: list[str], start: float, duration: float
) -> list[tuple[float, float, str]]:
    """Give each chunk a share of the narration time proportional to its length."""
    total = sum(len(c) for c in chunks) or 1
    t, out = start, []
    for c in chunks:
        d = duration * len(c) / total
        out.append((t, t + d, c))
        t += d
    return out


def kept_intervals(
    start: float, end: float, cuts: list[tuple[float, float]]
) -> list[tuple[float, float]]:
    """[start, end] minus the cut windows (clipped to the beat, merged if they overlap)."""
    keep, t = [], start
    for a, b in sorted((max(a, start), min(b, end)) for a, b in cuts):
        if b <= a:
            continue
        if a > t:
            keep.append((t, a))
        t = max(t, b)
    if end > t:
        keep.append((t, end))
    return keep


def cut_positions(start: float, cuts: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Where each cut lands on the beat's own (kept) clock, with the seconds removed."""
    out, removed = [], 0.0
    for a, b in sorted(cuts):
        out.append((a - start - removed, b - a))
        removed += b - a
    return out


def frame_list(
    frames: list[tuple[float, str]], intervals: list[tuple[float, float]]
) -> list[tuple[str, float]]:
    """(image, seconds) pairs showing what was on screen during each kept interval.

    Screencast frames arrive only when the page changes, so each frame lasts until the next one
    (or the end of the interval). The frame already showing when an interval starts opens it.
    """
    frames = sorted(frames)
    out: list[tuple[str, float]] = []
    for a, b in intervals:
        before = [f for f in frames if f[0] <= a]
        inside = [f for f in frames if a < f[0] < b]
        seq = ([(a, before[-1][1])] if before else []) + inside
        if not seq and frames:
            seq = [(a, frames[0][1])]
        for i, (t, path) in enumerate(seq):
            nxt = seq[i + 1][0] if i + 1 < len(seq) else b
            if nxt - t > 0:
                out.append((path, nxt - t))
    return out


def srt_time(t: float) -> str:
    ms = round(t * 1000)
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def srt(entries: list[tuple[float, float, str]]) -> str:
    return "".join(
        f"{i}\n{srt_time(a)} --> {srt_time(b)}\n{text}\n\n"
        for i, (a, b, text) in enumerate(entries, 1)
    )


# A full UK postcode (district + inward code), e.g. "N10 2AB". The app shows the district only.
POSTCODE = re.compile(r"\b[A-Z]{1,2}[0-9][A-Z0-9]? ?[0-9][ABD-HJLNP-UW-Z]{2}\b")


def privacy_problems(text: str, private_terms: list[str]) -> list[str]:
    """What must not be on screen: a full postcode, or any term the operator listed privately.

    Returns descriptions without the matched text, so nothing private reaches logs.
    """
    problems = []
    if POSTCODE.search(text):
        problems.append("a full postcode")
    lowered = text.lower()
    problems += [
        f"private term #{i}"
        for i, term in enumerate(private_terms, 1)
        if term and term.lower() in lowered
    ]
    return problems
