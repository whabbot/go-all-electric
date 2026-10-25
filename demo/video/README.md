# Demo video pipeline

Makes the 3-minute submission video from [`storyboard.yaml`](storyboard.yaml): Playwright drives
the app at 1280x800, Gemini TTS (`gemini-3.8-flash-tts`) voices each beat, ffmpeg cuts out long
waits and adds burned-in captions, and the result is a 1080p MP4 plus an `.srt`. No slides: the
footage is the app itself.

```bash
# From the repository root. Output defaults to the gitignored private/demo-video/.
uv run --project demo/video python demo/video/make_video.py draft
```

Edit a line of narration in `storyboard.yaml` and re-run the same command; only changed lines
are voiced again (they are cached by text and voice).

## How it works

- **Beats.** Each storyboard beat has a `draft` line, a `final` line and browser steps. The beat
  is held on screen at least as long as its narration (plus a short pause), so the voice never
  runs over the next screen. `make_video.py` warns when the video is over 3:00.
- **Voice.** Gemini TTS when `GEMINI_API_KEY` is set or in `~/.config/go-all-electric/.env`
  (read in code, never printed); otherwise macOS `say` (voice Daniel). Pick with
  `--voice-engine gemini|say` and `--voice` (Gemini default `Charon`).
- **Recording.** Chrome's own screencast, started only once the house is picked and the
  pre-roll photos are in, so the Start screen, postcode and address list never reach a frame.
  A drawn pointer shows clicks, because screencasts have no cursor.
- **Long waits.** A `wait_text`/`wait_gone` step with `trim: true` (photo check, analysis, quote
  check, Gemini review, drafts) is timed. Any wait over 4 s is cut down to its first 1.4 s and
  last 0.6 s, and a "Shortened: N s of waiting for the … cut" banner shows where the cut is.
- **Captions** are drawn with Pillow (this ffmpeg has no drawtext/subtitles filter) in a band
  under the app. The same text goes to `<name>.srt` for YouTube.
- **Privacy guard.** At every beat boundary the visible page text is checked for a full UK
  postcode and for any words you list in `GAE_PRIVATE_TERMS` (or at the prompt). A hit stops
  the run and deletes every recorded frame; the message never repeats the match.

## Modes

### `draft`: Sam's offline sample (no keys needed except for the Gemini voice)

```bash
uv run --project demo/video python demo/video/make_video.py draft [--out DIR]
```

It uses this worktree's mock instance, launching `launch.sh mock` if none is running and
stopping it afterwards. Photos are drawn synthetic stand-ins stamped "SYNTHETIC SAMPLE". Mock
results are canned, so the narration says Sam's sample and never presents the review or drafts
as live Gemini output. A side label reads "SAM'S SAMPLE, offline mock" throughout. The local
backend has no database, so the Atlas search beat shows a card saying so.

### `final`: the live site, your house (run it yourself)

```bash
GAE_ACCESS_CODE=... uv run --project demo/video python demo/video/make_video.py final \
  --url https://<live-site> --photos ~/private/redacted-photos \
  [--live-photo boiler-plate] [--live-box 0.6,0.8,0.95,0.95] [--insert atlas=~/atlas.mov]
```

1. A Chrome window opens. If the site asks for the access code, it is typed from
   `GAE_ACCESS_CODE` or a hidden prompt; it is never printed or logged. Then you are asked for
   optional private words (street name, house number) for the privacy guard.
2. **Nothing is recorded yet.** In the window, search your postcode, pick the house and press
   Continue. Recording starts by itself on the Photos step, which shows the district only.
3. Every photo in `--photos` except the live one is added first. Files are matched by name:
   `gas-bill*`, `boiler-plate*`, `fuse-cutout*`, `loft*`, `outdoor*` and `radiator-1*`,
   `radiator-2*`… (up to 3 per radiator). Each still goes through the app's Redact step, and
   you press **Use photo** yourself after checking each preview (`--confirm auto` skips that).
4. On camera, the `--live-photo` goes through Redact. `--live-box` draws one Black out box
   (fractions of the photo) to show the cover-up; leave it out for an already-clean photo.
5. Quotes are the three SAMPLE PDFs from `demo/quotes/`, uploaded and checked live. The review
   and the drafts are live Gemini calls, and their waits are cut.

Use only photos you have already redacted. The live run calls Gemini for real: one photo check,
the analysis, the review, three quote reads and three drafts. Raw frames of a final run are
always deleted after composing.

### `voiceover`: you record the screen, the pipeline does the voice

```bash
uv run --project demo/video python demo/video/make_video.py voiceover [--gap 2]
uv run --project demo/video python demo/video/make_video.py mux --video my-take.mov \
  --audio private/demo-video/voiceover-final.wav --out private/demo-video/final.mp4
```

This writes `voiceover-final.wav`, a timing sheet (`-timing.md`: start, end, what is on
screen, the line) and an `.srt`. Record with QuickTime while the track plays, following the
sheet, then `mux` lays the track over your recording at 1080p. Long waits do not fit this
path: use the finished second tab from the demo plan, or pause the recording.

### The Atlas console clip

Atlas console shots need your login, so they are not automated. Record about 12-20 s with
QuickTime: the Atlas Search tab (the two `datasheets` indexes), then Data Explorer, `surveys`,
newest document. Never show Network Access, Database Users or a connection string. Then pass
`--insert atlas=clip.mov`. The clip replaces the "Atlas console clip goes here" beat. It
plays in full, and a clip longer than the narration lengthens the beat. Before it,
the `atlas-search` beat shows the app's own `/api/datasheets/search` answer (hybrid mode,
`$rankFusion` fields highlighted) from whichever site is being recorded.

## Which to use for the final video

Recommended: **`final` mode**. It times every beat to the narration, cuts the 1-2 minute
Gemini waits cleanly, and the address never enters the recording. You still pick the house and
approve each photo. Use **`voiceover` + QuickTime** if the automated run trips on something
live: an unexpected photo verdict, an error, or the site wording changing.

## Tests

```bash
uv run --project demo/video pytest demo/video/tests
```

These cover the storyboard (both stories load, and the draft never claims live output), the
caption, cut and frame maths, photo-folder mapping, the privacy guard, the Atlas JSON page and
an ffmpeg render of an inserted clip. Rendered media (`*.mp4`, `*.wav`, …) is gitignored; never
commit video or audio.
