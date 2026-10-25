import shutil
import subprocess
from pathlib import Path

import pytest

from gaevideo import compose, graphics, record, storyboard
from gaevideo.record import BeatMarks

BOARD = Path(__file__).resolve().parent.parent / "storyboard.yaml"


@pytest.mark.parametrize("story", storyboard.STORIES)
def test_storyboard_loads_each_story(story):
    board = storyboard.load(BOARD, story)
    ids = [b.id for b in board.beats]
    assert ids[0] == "intro" and ids[-1] == "plan-pack"
    assert "atlas-console" in ids and board.voice_style
    for beat in board.beats:
        assert beat.narration and beat.actions
        for name, args in beat.actions:
            assert "only" not in args, (beat.id, name)


def test_story_filters_steps_and_keeps_honest_labels():
    draft = {b.id: b for b in storyboard.load(BOARD, "draft").beats}
    final = {b.id: b for b in storyboard.load(BOARD, "final").beats}
    assert any(
        n == "click" and "Load Sam's three quotes" in a.get("name", "")
        for n, a in draft["quotes"].actions
    )
    assert not any(n == "upload_quotes" for n, _ in draft["quotes"].actions)
    assert any(n == "upload_quotes" for n, _ in final["quotes"].actions)
    # Mock review and drafts are canned: the draft must not present them as live Gemini output.
    assert "sample" in draft["review"].narration.lower()
    assert not any("Draft all 3 emails" in a.get("name", "") for _, a in draft["plan-pack"].actions)
    for beat in draft.values():
        assert "my own house" not in beat.narration
    # Quotes are always called samples.
    assert (
        "sample" in draft["quotes"].narration.lower()
        and "sample" in final["quotes"].narration.lower()
    )


def test_rejects_multi_key_steps(tmp_path):
    bad = tmp_path / "b.yaml"
    bad.write_text(
        "beats:\n  - id: x\n    draft: hi\n    final: hi\n"
        "    actions:\n      - {wait: {s: 1}, click: {}}\n"
    )
    with pytest.raises(ValueError, match="one-key"):
        storyboard.load(bad, "draft")


def test_caption_chunks_fit_and_keep_all_words():
    text = (
        "Under the hood, MongoDB Atlas is the data store. Boiler plates and quoted models are "
        "matched against a datasheet library with Atlas hybrid search: full text plus vector, "
        "fused inside Atlas."
    )
    chunks = storyboard.caption_chunks(text, max_chars=60)
    assert all(len(c) <= 60 for c in chunks)
    assert " ".join(chunks).split() == text.split()


def test_caption_times_cover_the_narration():
    times = storyboard.caption_times(["ab", "abcd"], 0.5, 6.0)
    assert times[0] == (0.5, 2.5, "ab") and times[-1][1] == pytest.approx(6.5)


def test_kept_intervals_and_cut_positions():
    keep = storyboard.kept_intervals(10, 40, [(15, 25), (30, 32), (5, 11), (38, 50)])
    assert keep == [(11, 15), (25, 30), (32, 38)]
    assert storyboard.cut_positions(10, [(15, 25), (30, 32)]) == [(5, 10), (10, 2)]


def test_frame_list_holds_each_frame_until_the_next():
    frames = [(1.0, "a"), (3.0, "b"), (6.0, "c"), (9.0, "d")]
    # Interval 2-7 opens on the frame showing at 2 (a), then b and c; 8-10 opens on c, then d.
    assert storyboard.frame_list(frames, [(2, 7), (8, 10)]) == [
        ("a", 1.0),
        ("b", 3.0),
        ("c", 1.0),
        ("c", 1.0),
        ("d", 1.0),
    ]


def test_srt():
    out = storyboard.srt([(0, 1.25, "Hello"), (61.5, 3725.0, "Bye")])
    assert "00:00:00,000 --> 00:00:01,250\nHello" in out
    assert "00:01:01,500 --> 01:02:05,000\nBye" in out


def test_privacy_problems_never_echo_the_match():
    assert storyboard.privacy_problems("house in N10", []) == []
    found = storyboard.privacy_problems("Pick 14 Oakwood Avenue, N10 2AB", ["oakwood"])
    assert found == ["a full postcode", "private term #1"]
    assert "Oakwood" not in " ".join(found)


def test_photo_set_maps_files_to_slots(tmp_path):
    for name in [
        "Gas-Bill.jpg",
        "gas-bill-2.jpg",
        "boiler-plate.png",
        "radiator-2b.jpg",
        "radiator-2a.jpg",
        "radiator_1.jpeg",
        "radiator-1-x.png",
        "radiator-1-y.png",
        "radiator-1-z.png",
        "notes.txt",
        "fuse-cutout.heic",
    ]:
        (tmp_path / name).write_bytes(b"x")
    got = {k: [p.name for p in v] for k, v in record.photo_set(tmp_path).items()}
    assert list(got) == ["gas-bill", "boiler-plate", "radiator-1", "radiator-2"]
    assert got["gas-bill"] == ["Gas-Bill.jpg"]
    assert got["radiator-1"] == ["radiator-1-x.png", "radiator-1-y.png", "radiator-1-z.png"]
    assert got["radiator-2"] == ["radiator-2a.jpg", "radiator-2b.jpg"]


def test_json_page_highlights_atlas_fields_and_falls_back():
    body = (
        '{"mode": "hybrid", "fusion": "native_rank_fusion",'
        ' "matches": [{"produced_by": ["text", "vector"]}]}'
    )
    page = record.render_json_page("/api/datasheets/search?q=x", 200, body)
    assert '<b class="k">&quot;fusion&quot;</b>' in page and "native_rank_fusion" in page
    fallback = record.render_json_page(
        "/api/datasheets/search?q=x", 503, '{"detail": "unavailable"}'
    )
    assert "HTTP 503" in fallback and "live run" in fallback


def test_synthetic_photos_are_marked(tmp_path):
    made = graphics.synth_photos(tmp_path)
    assert set(made) == {"gas-bill", "boiler-plate", "fuse-cutout", "radiator-1"}
    assert all(p.stat().st_size > 1000 for p in made.values())


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
def test_beat_clip_with_insert_and_with_frames(tmp_path):
    wav = tmp_path / "n.wav"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=f=440:d=2", str(wav)], check=True
    )
    clip = tmp_path / "insert.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=1280x720:rate=30",
            "-t",
            "4.5",
            "-pix_fmt",
            "yuv420p",
            str(clip),
        ],
        check=True,
    )
    mark = BeatMarks("x", start=100.0, end=104.0, cuts=[(101.0, 102.0, "review")])
    out, length, caps = compose.beat_clip(
        0, "x", "One line. Two lines.", mark, [], (wav, 2.0), tmp_path, None, clip
    )
    # The 4.5 s clip outlasts the 3 s of kept footage, so the whole clip plays.
    assert length == pytest.approx(4.5, abs=0.05) and len(caps) == 2
    assert compose.probe_duration(out) == pytest.approx(4.5, abs=0.15)

    frame = tmp_path / "f.jpg"
    graphics.card("t", "b", frame)
    out2, length2, _ = compose.beat_clip(
        1, "y", "Hi.", mark, [(99.0, str(frame))], (wav, 2.0), tmp_path, ["SAMPLE"], None
    )
    assert compose.probe_duration(out2) == pytest.approx(length2, abs=0.15)


def test_draft_atlas_beats_never_show_a_database_error():
    draft = {b.id: b for b in storyboard.load(BOARD, "draft").beats}
    for beat_id in ("atlas-search", "atlas-console"):
        beat = draft[beat_id]
        assert beat.insert == "atlas"
        assert not any(n == "json_tab" for n, _ in beat.actions)
        text = " ".join(a.get("body", "") + a.get("title", "") for _, a in beat.actions).lower()
        assert "503" not in text and "no database" not in text and "goes here" not in text


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
def test_one_insert_clip_covers_both_atlas_beats(tmp_path):
    import make_video

    beats = storyboard.load(BOARD, "draft").beats
    voices = []
    for k in range(len(beats)):
        wav = tmp_path / f"v{k}.wav"
        subprocess.run(
            ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=f=440:d=2", str(wav)],
            check=True,
        )
        voices.append((wav, 2.0))
    marks = [BeatMarks(b.id, start=10.0 * k, end=10.0 * k + 3.0) for k, b in enumerate(beats)]
    clip = tmp_path / "atlas.mov"
    clip.write_bytes(b"x")

    segs = list(make_video._segments(beats, marks, voices, {"atlas": clip}, tmp_path))
    assert len(segs) == len(beats) - 1
    (seg,) = [s for s in segs if s[4] is not None]
    seg_id, narration, mark, (wav, secs), insert, labels = seg
    assert seg_id == "atlas-search+atlas-console" and insert == clip
    by_id = {b.id: b for b in beats}
    assert by_id["atlas-search"].narration in narration
    assert by_id["atlas-console"].narration in narration
    # Both lines play, with the usual pause between beats.
    assert secs == pytest.approx(4.0 + record.TAIL + record.LEAD, abs=0.05)
    assert compose.probe_duration(wav) >= secs
    assert mark.start == marks[7].start and mark.end == marks[8].end
    # Real footage gets its own labels, switching where the second beat starts.
    assert [(text, a) for text, a, _ in labels] == [
        (["LIVE SITE", "real footage"], 0.0),
        (["MONGODB", "Atlas console", "real footage"], 3.0),
    ]
    assert labels[0][2] == 3.0

    # Without a clip every beat stays its own segment.
    plain = list(make_video._segments(beats, marks, voices, {}, tmp_path))
    assert [s[0] for s in plain] == [b.id for b in beats]
    assert all(s[5] is None for s in plain)
