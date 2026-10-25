"""Make the Go All-Electric demo video from storyboard.yaml (see README.md).

draft      record Sam's offline sample on a local mock instance (launched if needed)
final      record the live site with your own redacted photos (house picked off-camera)
voiceover  narration track + timing sheet only, for recording the screen yourself
mux        your own screen recording + the voiceover track -> MP4
"""

import argparse
import getpass
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))

from gaevideo import compose, graphics, record, storyboard  # noqa: E402
from gaevideo.voice import Voice  # noqa: E402

SKILL = REPO / ".agents/skills/verify-go-all-electric/scripts"
LIMIT_S = 180.0
DRAFT_BADGE = ["SAM'S SAMPLE", "offline mock", "canned results,", "no live calls"]


def log(msg: str) -> None:
    print(f"make_video: {msg}", file=sys.stderr, flush=True)


def _mock_url() -> tuple[str, bool]:
    """A running mock instance from this worktree, or a new one (torn down afterwards)."""
    env = REPO / ".verify/run/env"
    if env.exists():
        vals = dict(
            line.removeprefix("export ").split("=", 1)
            for line in env.read_text().splitlines()
            if "=" in line
        )
        alive = all(_alive(vals.get(k)) for k in ("GAE_BACKEND_PID", "GAE_FRONTEND_PID"))
        if alive and vals.get("GAE_MODE") == "mock":
            return vals["GAE_URL"], False
        if alive:
            raise SystemExit(
                f"make_video: a {vals.get('GAE_MODE')} instance is running here; "
                "draft needs mock (run teardown.sh first)"
            )
    out = subprocess.run(
        [str(SKILL / "launch.sh"), "mock"], check=True, capture_output=True, text=True
    ).stdout
    url = next(line.split()[1] for line in out.splitlines() if line.strip().startswith("app"))
    return url, True


def _alive(pid: str | None) -> bool:
    try:
        os.kill(int(pid or ""), 0)
        return True
    except ValueError, OSError:
        return False


def _box(text: str | None) -> tuple[float, float, float, float] | None:
    if not text:
        return None
    vals = tuple(float(v) for v in text.split(","))
    if len(vals) != 4 or not all(0 <= v <= 1 for v in vals):
        raise SystemExit("--live-box takes four fractions x1,y1,x2,y2 between 0 and 1")
    return vals  # type: ignore[return-value]


def _inserts(items: list[str]) -> dict[str, Path]:
    out = {}
    for item in items:
        name, _, path = item.partition("=")
        p = Path(path).expanduser()
        if not p.is_file():
            raise SystemExit(f"--insert {name}: no such file {p}")
        out[name] = p
    return out


def _segments(beats, marks, voices, inserts, work):
    """(id, narration, marks, voice, clip) per segment. Consecutive beats sharing a supplied
    insert clip become one segment: the clip plays under all their lines, which keep the usual
    pause between beats, and the segment lasts as long as the clip or the footage, if longer."""
    groups: list[list[int]] = []
    for i, beat in enumerate(beats):
        name = beat.insert if beat.insert in inserts else None
        if groups and name and beats[groups[-1][-1]].insert == name:
            groups[-1].append(i)
        else:
            groups.append([i])
    for g in groups:
        first, last = beats[g[0]], beats[g[-1]]
        insert = inserts.get(first.insert or "")
        if len(g) == 1:
            yield first.id, first.narration, marks[g[0]], voices[g[0]], insert
            continue
        seg_id = f"{first.id}+{last.id}"
        wav = work / f"{seg_id}.wav"
        times = compose.voiceover_track([voices[i] for i in g], record.TAIL + record.LEAD, wav)
        mark = record.BeatMarks(
            seg_id,
            start=marks[g[0]].start,
            end=marks[g[-1]].end,
            cuts=[c for i in g for c in marks[i].cuts],
        )
        yield seg_id, " ".join(beats[i].narration for i in g), mark, (wav, times[-1][1]), insert


def _secret(env: str, prompt: str) -> str | None:
    if os.environ.get(env):
        return os.environ[env]
    if sys.stdin.isatty():
        return getpass.getpass(prompt) or None
    return None


def _write_narration(
    path: Path, title: str, voice_label: str, rows: list[tuple[str, float, float, str]]
) -> None:
    lines = [f"# {title}", "", f"Voice: {voice_label}", ""]
    for beat_id, a, b, text in rows:
        lines += [f"## {beat_id}  ({a:.1f}s - {b:.1f}s)", "", text, ""]
    path.write_text("\n".join(lines))


def make(args: argparse.Namespace) -> None:
    out_dir = Path(args.out).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    name = args.name or args.cmd
    work = out_dir / f".work-{name}"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir()

    board = storyboard.load(HERE / "storyboard.yaml", args.story)
    voice = Voice(args.voice_engine, args.voice, board.voice_style, out_dir / ".voice-cache")
    log(f"voicing {len(board.beats)} beats with {voice.label()}")
    voices = voice.speak_all([b.narration for b in board.beats])
    spoken = sum(s for _, s in voices)
    log(f"narration: {spoken:.1f}s spoken")

    inserts = _inserts(args.insert or [])
    torn_down = False
    if args.cmd == "draft":
        url, launched = (args.url, False) if args.url else _mock_url()
        photos = {k: [v] for k, v in graphics.synth_photos(work / "synthetic").items()}
        opts = record.Options(
            story=args.story,
            url=url,
            photos=photos,
            live_photo="gas-bill",
            live_box=graphics.BILL_IDENTITY_BOX,
            house="sample",
            confirm="auto",
            headed=args.headed,
            access_code=None,
            private_terms=[],
            repo=REPO,
        )
        badge = DRAFT_BADGE
    else:
        launched = False
        folder = Path(args.photos).expanduser()
        photos = record.photo_set(folder)
        if not photos:
            raise SystemExit(
                f"final: no photos named gas-bill*, boiler-plate*, radiator-1* ... in {folder}"
            )
        if args.live_photo not in photos:
            raise SystemExit(
                f"final: --live-photo {args.live_photo} has no file in the photos folder"
            )
        found = ", ".join(f"{k} x{len(v)}" for k, v in photos.items())
        log(f"photos: {found}; live on camera: {args.live_photo}")
        code = _secret("GAE_ACCESS_CODE", "Access code (Enter if the site has none): ")
        terms_raw = _secret(
            "GAE_PRIVATE_TERMS",
            "Words that must never be on screen, e.g. street, house number "
            "(comma-separated, Enter for none): ",
        )
        opts = record.Options(
            story=args.story,
            url=args.url,
            photos=photos,
            live_photo=args.live_photo,
            live_box=_box(args.live_box),
            house=args.house,
            confirm=args.confirm,
            headed=not args.headless,
            access_code=code,
            private_terms=[t.strip() for t in (terms_raw or "").split(",") if t.strip()],
            repo=REPO,
        )
        badge = None

    frames_dir = work / "frames"
    try:
        marks, rec = record.record(opts, board.beats, [s for _, s in voices], frames_dir)
    except record.PrivacyStop as e:
        shutil.rmtree(work, ignore_errors=True)
        raise SystemExit(f"make_video: STOPPED, {e}. All recorded frames were deleted.") from None
    finally:
        if launched and not args.keep_instance:
            subprocess.run([str(SKILL / "teardown.sh")], capture_output=True)
            torn_down = True
    log(f"recorded {len(rec.frames)} frames; composing")

    clips, entries, rows, t = [], [], [], 0.0
    for i, (beat_id, narration, mark, v, insert) in enumerate(
        _segments(board.beats, marks, voices, inserts, work)
    ):
        clip, length, caps = compose.beat_clip(
            i, beat_id, narration, mark, rec.frames, v, work, badge, insert
        )
        clips.append(clip)
        entries += [(t + a, t + b, text) for a, b, text in caps]
        rows.append((beat_id, t, t + length, narration))
        t += length
    video = out_dir / f"{name}.mp4"
    compose.join(clips, video)
    (out_dir / f"{name}.srt").write_text(storyboard.srt(entries))
    _write_narration(
        out_dir / f"{name}.narration.md",
        f"Narration: {name} ({args.story} story)",
        voice.label(),
        rows,
    )

    total = compose.probe_duration(video)
    if not args.keep_work:
        shutil.rmtree(work, ignore_errors=True)
    elif args.cmd == "final":
        shutil.rmtree(frames_dir, ignore_errors=True)  # never keep raw frames of a live run
    over = "" if total <= LIMIT_S else ", OVER the 3:00 limit: shorten the narration"
    log(f"wrote {video} ({total:.1f}s{over})")
    if torn_down:
        log("mock instance stopped")
    print(video)


def voiceover(args: argparse.Namespace) -> None:
    out_dir = Path(args.out).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    board = storyboard.load(HERE / "storyboard.yaml", args.story)
    voice = Voice(args.voice_engine, args.voice, board.voice_style, out_dir / ".voice-cache")
    voices = voice.speak_all([b.narration for b in board.beats])
    name = args.name or f"voiceover-{args.story}"
    track = out_dir / f"{name}.wav"
    times = compose.voiceover_track(voices, args.gap, track)
    entries = []
    sheet = [
        f"# Timing sheet: {name}",
        "",
        f"Voice: {voice.label()}. Total {times[-1][1]:.1f}s with {args.gap:.1f}s between "
        f"lines. Start your screen recording, then play `{track.name}`; do each row's screen "
        "action while its line plays. Then: "
        f"`make_video.py mux --video YOURS.mov --audio {track.name}`.",
        "",
        "| Start | End | On screen | Line |",
        "| --- | --- | --- | --- |",
    ]
    for beat, (a, b) in zip(board.beats, times, strict=True):
        sheet.append(f"| {_mmss(a)} | {_mmss(b)} | {beat.screen} | {beat.narration} |")
        entries += [
            (a + x, a + y, text)
            for x, y, text in storyboard.caption_times(
                storyboard.caption_chunks(beat.narration), 0, b - a
            )
        ]
    (out_dir / f"{name}-timing.md").write_text("\n".join(sheet) + "\n")
    (out_dir / f"{name}.srt").write_text(storyboard.srt(entries))
    log(f"wrote {track}, {name}-timing.md and {name}.srt ({times[-1][1]:.1f}s)")
    print(track)


def mux(args: argparse.Namespace) -> None:
    out = Path(args.out).expanduser()
    compose.mux(Path(args.video).expanduser(), Path(args.audio).expanduser(), out)
    log(f"wrote {out} ({compose.probe_duration(out):.1f}s)")
    print(out)


def _mmss(t: float) -> str:
    return f"{int(t // 60)}:{t % 60:04.1f}"


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    default_out = str(REPO / "private/demo-video")

    def voice_opts(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--voice-engine",
            choices=["auto", "gemini", "say"],
            default="auto",
            help="auto = Gemini TTS when a key is configured, else macOS say",
        )
        p.add_argument(
            "--voice", help="Gemini voice (default Charon) or say voice (default Daniel)"
        )
        p.add_argument(
            "--out",
            default=default_out,
            help="output folder (default: gitignored private/demo-video)",
        )
        p.add_argument("--name", help="output file name stem")

    def record_opts(p: argparse.ArgumentParser) -> None:
        voice_opts(p)
        p.add_argument(
            "--insert",
            action="append",
            metavar="NAME=PATH",
            help="use a clip for a beat's footage, e.g. atlas=atlas.mov (both Atlas beats)",
        )
        p.add_argument(
            "--keep-work", action="store_true", help="keep per-beat clips (never live frames)"
        )

    d = sub.add_parser("draft", help="Sam's offline sample on a local mock instance")
    record_opts(d)
    d.add_argument(
        "--url", help="a running mock instance (default: this worktree's, launched if needed)"
    )
    d.add_argument("--headed", action="store_true", help="show the browser window")
    d.add_argument(
        "--keep-instance", action="store_true", help="leave a mock instance it launched running"
    )
    d.set_defaults(story="draft", func=make)

    f = sub.add_parser("final", help="the live site with your own already-redacted photos")
    record_opts(f)
    f.add_argument("--url", required=True, help="the site to record (live URL)")
    f.add_argument(
        "--photos",
        required=True,
        help="folder of redacted photos: gas-bill*, boiler-plate*, radiator-1* ...",
    )
    f.add_argument(
        "--live-photo",
        default="boiler-plate",
        help="the one photo added on camera (default boiler-plate)",
    )
    f.add_argument(
        "--live-box", help="Black out drag on camera, as fractions x1,y1,x2,y2 of the photo"
    )
    f.add_argument(
        "--house",
        choices=["manual", "sample"],
        default="manual",
        help="manual: you pick the house in the window before recording (sample: mock testing)",
    )
    f.add_argument(
        "--confirm",
        choices=["manual", "auto"],
        default="manual",
        help="manual: you press Use photo on every Redact preview",
    )
    f.add_argument(
        "--headless",
        action="store_true",
        help="no window (only with --house sample --confirm auto)",
    )
    f.add_argument("--story", choices=storyboard.STORIES, default="final")
    f.set_defaults(func=make, keep_instance=False)

    v = sub.add_parser(
        "voiceover", help="narration track + timing sheet for recording the screen yourself"
    )
    voice_opts(v)
    v.add_argument("--story", choices=storyboard.STORIES, default="final")
    v.add_argument("--gap", type=float, default=2.0, help="seconds between lines (default 2)")
    v.set_defaults(func=voiceover)

    m = sub.add_parser("mux", help="your screen recording + the voiceover track")
    m.add_argument("--video", required=True)
    m.add_argument("--audio", required=True)
    m.add_argument("--out", required=True, help="output .mp4")
    m.set_defaults(func=mux)

    args = ap.parse_args()
    if (
        args.cmd == "final"
        and args.headless
        and (args.house == "manual" or args.confirm == "manual")
    ):
        raise SystemExit(
            "final: --headless needs --house sample --confirm auto "
            "(nobody can click in a hidden window)"
        )
    t0 = time.time()
    args.func(args)
    log(f"done in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
