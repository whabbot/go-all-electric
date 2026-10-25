"""Drive the app through the storyboard with Playwright and record it with Chrome's screencast.

Recording starts only once the house is picked and the photos that are not shown live are in
(the "pre-roll"), so the Start screen, postcode and address list never reach the frames. Long
waits are timed here and cut later; every beat is held until its narration fits.
"""

import base64
import contextlib
import html
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from playwright.sync_api import Locator, Page, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeout

from gaevideo.storyboard import Beat, privacy_problems

VIEWPORT = {"width": 1280, "height": 800}
SCALE = 1.5  # device pixels, so the screencast frames are 1920x1200
LEAD = 0.35  # narration starts this long after the beat does
TAIL = 0.7  # quiet after the narration before the next beat
TRIM_MIN = float(os.environ.get("GAE_VIDEO_TRIM_MIN", "4"))  # shorter waits stay in the video
TRIM_HEAD, TRIM_TAIL = 1.4, 0.6  # seconds of a long wait kept either side of the cut

PHOTO_SLOTS = {
    "gas-bill": "Gas bill",
    "loft": "Loft",
    "boiler-plate": "Boiler data plate",
    "fuse-cutout": "Fuse cutout",
    "outdoor": "Outdoor unit spot",
}
PHOTO_EXT = {".jpg", ".jpeg", ".png", ".webp"}

# A drawn pointer that follows the mouse (screencasts do not include the OS cursor) and rings
# on click. Pointer events, because the Redact canvas suppresses the compatibility mouse events.
CURSOR_JS = """
(() => {
  const add = () => {
    if (document.getElementById('__demo_cursor')) return;
    const c = document.createElement('div');
    c.id = '__demo_cursor';
    c.innerHTML = '<svg width="28" height="28" viewBox="0 0 28 28"><path d="M3 2 L3 22 L8.5 17 L12.5 26 L16 24.5 L12 15.8 L19.5 15.8 Z" fill="#111" stroke="#fff" stroke-width="1.6"/></svg>';
    Object.assign(c.style, {position: 'fixed', left: '-40px', top: '-40px', zIndex: 2147483647,
      pointerEvents: 'none', width: '28px', height: '28px', transition: 'none'});
    document.documentElement.appendChild(c);
    const move = (e) => { c.style.left = e.clientX - 3 + 'px'; c.style.top = e.clientY - 2 + 'px'; };
    addEventListener('pointermove', move, true);
    addEventListener('pointerdown', (e) => {
      move(e);
      const r = document.createElement('div');
      Object.assign(r.style, {position: 'fixed', left: e.clientX - 18 + 'px', top: e.clientY - 18 + 'px',
        width: '36px', height: '36px', borderRadius: '50%', border: '3px solid rgba(232,120,30,.9)',
        zIndex: 2147483646, pointerEvents: 'none', transition: 'transform .45s ease-out, opacity .45s ease-out'});
      document.documentElement.appendChild(r);
      requestAnimationFrame(() => { r.style.transform = 'scale(1.8)'; r.style.opacity = '0'; });
      setTimeout(() => r.remove(), 600);
    }, true);
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', add); else add();
})();
"""


class PrivacyStop(Exception):
    """Something private is on screen: recording stops and the frames are discarded."""


def photo_set(folder: Path) -> dict[str, list[Path]]:
    """Map a folder of already-redacted photos to app slots by file name.

    gas-bill*, loft*, boiler-plate*, fuse-cutout*, outdoor* (first match each), radiator-<n>*
    (up to 3 photos per radiator, in name order). Anything else is ignored.
    """
    files = sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in PHOTO_EXT)
    out: dict[str, list[Path]] = {}
    for p in files:
        name = p.stem.lower()
        m = re.match(r"radiator[-_ ]?(\d+)", name)
        if m:
            key = f"radiator-{int(m.group(1))}"
            if len(out.setdefault(key, [])) < 3:
                out[key].append(p)
            continue
        for key in PHOTO_SLOTS:
            if name.startswith(key) and key not in out:
                out[key] = [p]
    return dict(sorted(out.items(), key=lambda kv: _slot_order(kv[0])))


def _slot_order(key: str) -> tuple[int, int]:
    order = list(PHOTO_SLOTS)
    if key.startswith("radiator-"):
        return (len(order), int(key.split("-")[1]))
    return (order.index(key), 0)


@dataclass
class BeatMarks:
    id: str
    start: float = 0.0
    end: float = 0.0
    cuts: list[tuple[float, float, str]] = field(default_factory=list)

    def kept(self, now: float) -> float:
        return (now - self.start) - sum(b - a for a, b, _ in self.cuts)


class Recorder:
    """Chrome screencast frames (JPEG, with Chrome's own timestamps) for whichever tab is shown."""

    def __init__(self, frames_dir: Path):
        self.dir = frames_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        self.frames: list[tuple[float, str]] = []
        self.cdp = None
        self.offset: float | None = None

    def _on_frame(self, params: dict) -> None:
        now = time.time()
        ts = params.get("metadata", {}).get("timestamp")
        if ts is None:
            ts = now
        if self.offset is None:  # Chrome's clock should be epoch seconds; correct it if not
            self.offset = now - ts if abs(now - ts) > 5 else 0.0
        path = self.dir / f"{len(self.frames):06d}.jpg"
        path.write_bytes(base64.b64decode(params["data"]))
        self.frames.append((ts + self.offset, str(path)))
        with contextlib.suppress(Exception):  # the tab may have closed between frame and ack
            self.cdp.send("Page.screencastFrameAck", {"sessionId": params["sessionId"]})

    def attach(self, page: Page) -> None:
        self.detach()
        self.cdp = page.context.new_cdp_session(page)
        self.cdp.on("Page.screencastFrame", self._on_frame)
        self.cdp.send(
            "Page.startScreencast",
            {
                "format": "jpeg",
                "quality": 90,
                "everyNthFrame": 1,
                "maxWidth": int(VIEWPORT["width"] * SCALE),
                "maxHeight": int(VIEWPORT["height"] * SCALE),
            },
        )

    def detach(self) -> None:
        if self.cdp is not None:
            try:
                self.cdp.send("Page.stopScreencast")
                self.cdp.detach()
            except Exception:
                pass
            self.cdp = None


@dataclass
class Options:
    story: str
    url: str
    photos: dict[str, list[Path]]
    live_photo: str
    live_box: tuple[float, float, float, float] | None
    house: str  # sample | manual
    confirm: str  # auto | manual
    headed: bool
    access_code: str | None
    private_terms: list[str]
    repo: Path


def log(msg: str) -> None:
    print(f"record: {msg}", file=sys.stderr, flush=True)


class Director:
    def __init__(self, page: Page, rec: Recorder, opts: Options):
        self.page = page  # the app tab
        self.shown = page  # the tab being recorded
        self.rec = rec
        self.opts = opts
        self.marks: list[BeatMarks] = []
        self.side_tab: Page | None = None

    # --- pointer helpers -------------------------------------------------------------------
    def _move_to(self, loc: Locator) -> tuple[float, float]:
        loc.wait_for(state="visible", timeout=15_000)
        # Keep targets clear of the sticky step bar and the fixed Back/Next bar; leave elements
        # that live in those bars where they are.
        moved = self.shown.evaluate(
            """(e) => {
              for (let p = e; p; p = p.parentElement) {
                const pos = getComputedStyle(p).position;
                if (pos === 'fixed' || pos === 'sticky') return false;
              }
              const r = e.getBoundingClientRect();
              if (r.top >= 140 && r.bottom <= innerHeight - 110) return false;
              const room = innerHeight - 250;
              window.scrollTo({top: r.top + scrollY - 140 - Math.max(0, (room - r.height) / 3), behavior: 'smooth'});
              return true;
            }""",
            loc.element_handle(),
        )
        if moved:
            self.shown.wait_for_timeout(900)
        box = loc.bounding_box()
        if box is None:
            raise RuntimeError("element has no box")
        x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        self.shown.mouse.move(x, y, steps=22)
        self.shown.wait_for_timeout(180)
        return x, y

    def _click(self, loc: Locator) -> None:
        self._move_to(loc)
        loc.click(timeout=10_000)
        self.shown.wait_for_timeout(250)

    def _visible(self, loc: Locator) -> Locator:
        for i in range(loc.count()):
            if loc.nth(i).is_visible():
                return loc.nth(i)
        return loc.first

    def _smooth_scroll(self, top_js: str) -> None:
        self.shown.evaluate(f"() => window.scrollTo({{top: {top_js}, behavior: 'smooth'}})")
        self.shown.wait_for_timeout(1000)

    # --- privacy ---------------------------------------------------------------------------
    def check_privacy(self, where: str) -> None:
        problems = privacy_problems(self.shown.inner_text("body"), self.opts.private_terms)
        if problems:
            raise PrivacyStop(f"{', '.join(problems)} visible at {where}")

    # --- photos ----------------------------------------------------------------------------
    def _slot_input(self, key: str) -> Locator:
        if key.startswith("radiator-"):
            n = key.split("-")[1]
            return self.page.locator(f'input[aria-label="Add photos of Radiator {n}"]')
        label = PHOTO_SLOTS[key]
        return (
            self.page.locator("li")
            .filter(has=self.page.locator(".capture-guide-label", has_text=label))
            .locator("input[type=file]")
            .first
        )

    def _ensure_radiator(self, key: str) -> None:
        n = int(key.split("-")[1])
        while self.page.locator('input[aria-label^="Add photos of Radiator"]').count() < n:
            self._click(self._visible(self.page.get_by_role("button", name="+ Add radiator")))

    def _confirm_coverup(self, live: bool) -> None:
        dialog = self.page.locator('[role=dialog][aria-labelledby="cover-up-title"]')
        dialog.wait_for(state="visible", timeout=15_000)
        if self.opts.confirm == "manual":
            print(
                "\n>>> Check the Redact preview in the browser window. Black out anything identifying,"
                " then press 'Use photo' (for every photo in the queue).",
                file=sys.stderr,
                flush=True,
            )
            dialog.wait_for(state="hidden", timeout=15 * 60_000)
            return
        while dialog.is_visible():
            button = dialog.get_by_role("button", name="Use photo")
            button.wait_for(state="visible", timeout=10_000)
            if live:
                self._click(button)
            else:
                button.click()
            self.page.wait_for_timeout(500)

    def preload_photos(self) -> None:
        for key, files in self.opts.photos.items():
            if key == self.opts.live_photo:
                continue
            log(f"pre-roll: adding {key} ({len(files)} photo{'s' if len(files) > 1 else ''})")
            if key.startswith("radiator-"):
                self._ensure_radiator(key)
            self._slot_input(key).set_input_files([str(p) for p in files])
            self._confirm_coverup(live=False)
        self.page.get_by_text("Checking photo").first.wait_for(state="hidden", timeout=180_000)

    def live_photo(self) -> None:
        key = self.opts.live_photo
        files = self.opts.photos.get(key)
        if not files:
            raise SystemExit(f"record: no photo for the live slot {key!r} in the photos folder")
        if key.startswith("radiator-"):
            self._ensure_radiator(key)
            trigger = self.page.locator("label").filter(has=self._slot_input(key))
        else:
            trigger = (
                self.page.locator("li")
                .filter(has=self.page.locator(".capture-guide-label", has_text=PHOTO_SLOTS[key]))
                .locator("label.capture-slot-upload")
                .first
            )
        self._move_to(trigger)
        with self.page.expect_file_chooser() as chooser:
            trigger.click()
        chooser.value.set_files([str(p) for p in files])
        dialog = self.page.locator('[role=dialog][aria-labelledby="cover-up-title"]')
        dialog.wait_for(state="visible", timeout=15_000)
        self.page.wait_for_timeout(1200)
        if self.opts.live_box:
            self._click(dialog.get_by_role("button", name="Black out"))
            img = dialog.locator(".cover-up-image").bounding_box()
            x1, y1, x2, y2 = self.opts.live_box
            p = self.page.mouse
            p.move(img["x"] + x1 * img["width"], img["y"] + y1 * img["height"], steps=15)
            p.down()
            p.move(img["x"] + x2 * img["width"], img["y"] + y2 * img["height"], steps=25)
            p.up()
            self.page.wait_for_timeout(900)
        self._confirm_coverup(live=True)

    def upload_quotes(self, files: list[str]) -> None:
        paths = [str(self.opts.repo / f) for f in files]
        trigger = self.page.locator("label").filter(has_text="Choose PDFs or photos").first
        self._move_to(trigger)
        with self.page.expect_file_chooser() as chooser:
            trigger.click()
        chooser.value.set_files(paths)
        dialog = self.page.locator('[role=dialog][aria-labelledby="cover-up-title"]')
        dialog.wait_for(state="visible", timeout=30_000)
        while dialog.is_visible():  # SAMPLE quote pages: synthetic, confirmed automatically
            button = dialog.get_by_role("button", name="Use photo")
            button.wait_for(state="visible", timeout=30_000)
            self.page.wait_for_timeout(500)
            button.click()
            self.page.wait_for_timeout(600)
        self._click(self.page.get_by_role("button", name="Check quotes"))

    # --- the second tab (Atlas search result, insert placeholder) ---------------------------
    def json_tab(self, path: str) -> None:
        result = self.page.evaluate(
            """async (p) => { try { const r = await fetch(p, {credentials: 'same-origin'});
                 return {status: r.status, body: await r.text()} } catch (e) { return {status: 0, body: String(e)} } }""",
            path,
        )
        self.side_tab = self.page.context.new_page()
        self.side_tab.set_content(render_json_page(path, result["status"], result["body"]))
        self.side_tab.bring_to_front()
        self.shown = self.side_tab
        self.rec.attach(self.side_tab)
        log(f"json tab: {path.split('?')[0]} -> HTTP {result['status']}")

    def insert_card(self, title: str, body: str) -> None:
        if self.side_tab is None:
            self.side_tab = self.page.context.new_page()
            self.side_tab.bring_to_front()
            self.shown = self.side_tab
            self.rec.attach(self.side_tab)
        self.side_tab.set_content(render_card_page(title, body))
        self.side_tab.wait_for_timeout(300)

    def back_to_app(self) -> None:
        if self.side_tab is not None:
            self.page.bring_to_front()
            self.shown = self.page
            self.rec.attach(self.page)
            self.side_tab.close()
            self.side_tab = None
            # A fresh screencast sends a frame only when something paints: nudge one.
            self.page.mouse.move(640, 420, steps=4)
            self.page.wait_for_timeout(300)

    # --- steps -----------------------------------------------------------------------------
    def _timed_wait(self, mark: BeatMarks, args: dict, gone: bool) -> None:
        t0 = time.time()
        loc = self.shown.get_by_text(args["text"]).first
        loc.wait_for(
            state="hidden" if gone else "visible", timeout=float(args.get("timeout", 60)) * 1000
        )
        t1 = time.time()
        waited = t1 - t0
        if args.get("trim") and waited > max(TRIM_MIN, TRIM_HEAD + TRIM_TAIL + 0.3):
            mark.cuts.append((t0 + TRIM_HEAD, t1 - TRIM_TAIL, args.get("label", "wait")))
            log(f"  waited {waited:.1f}s for {args.get('label', args['text'])}: cut from the video")
        else:
            log(f"  waited {waited:.1f}s for {args.get('label', args['text'])}")

    def step(self, mark: BeatMarks, name: str, args: dict) -> None:
        pg = self.shown
        if name == "click":
            scope = pg.get_by_role("navigation", name="Guided flow") if args.get("nav") else pg
            self._click(
                self._visible(
                    scope.get_by_role(
                        args["role"], name=args["name"], exact=args.get("exact", False)
                    )
                )
            )
        elif name == "point":
            if "role" in args:
                self._move_to(self._visible(pg.get_by_role(args["role"], name=args["name"])))
            else:
                self._move_to(self._visible(pg.get_by_text(args["text"])))
        elif name == "tick":
            self._click(self._visible(pg.get_by_label(args["label"])))
        elif name == "scroll_to":
            el = self._visible(pg.get_by_text(args["text"]))
            el.wait_for(state="attached", timeout=15_000)
            handle = el.element_handle()
            pg.evaluate(
                "(e) => window.scrollTo({top: e.getBoundingClientRect().top + window.scrollY - 130,"
                " behavior: 'smooth'})",
                handle,
            )
            pg.wait_for_timeout(1000)
        elif name == "scroll_top":
            self._smooth_scroll("0")
        elif name == "scroll_by":
            self._smooth_scroll(f"window.scrollY + {int(args['px'])}")
        elif name == "wait":
            pg.wait_for_timeout(float(args["s"]) * 1000)
        elif name in ("wait_text", "wait_gone"):
            self._timed_wait(mark, args, gone=name == "wait_gone")
        elif name == "live_photo":
            self.live_photo()
        elif name == "upload_quotes":
            self.upload_quotes(args["files"])
        elif name == "json_tab":
            self.json_tab(args["path"])
        elif name == "insert_card":
            self.insert_card(args["title"], args["body"])
        elif name == "back_to_app":
            self.back_to_app()
        else:
            raise ValueError(f"unknown step {name!r}")

    def play(self, beat: Beat, narration_s: float) -> BeatMarks:
        mark = BeatMarks(beat.id, start=time.time())
        self.marks.append(mark)
        log(f"beat {beat.id} (narration {narration_s:.1f}s)")
        self.check_privacy(f"start of {beat.id}")
        for name, args in beat.actions:
            try:
                self.step(mark, name, args)
            except PlaywrightTimeout as e:
                raise RuntimeError(
                    f"beat {beat.id}, step {name} {args}: timed out ({str(e).splitlines()[0]})"
                ) from None
        need = LEAD + narration_s + TAIL
        while mark.kept(time.time()) < need:
            self.shown.wait_for_timeout(min(250, (need - mark.kept(time.time())) * 1000 + 10))
        self.check_privacy(f"end of {beat.id}")
        mark.end = time.time()
        return mark


def render_json_page(path: str, status: int, body: str) -> str:
    """The app's own API answer, pretty-printed, with the Atlas fields highlighted."""
    try:
        pretty = json.dumps(json.loads(body), indent=2, ensure_ascii=False) if status == 200 else ""
    except ValueError:
        pretty = ""
    if not pretty:
        note = (
            "This local sample has no database, so the API answered "
            f"HTTP {status}. The live run shows the Atlas hybrid-search result here."
        )
        return render_card_page("Atlas hybrid search", note, sub=f"GET {path}")
    text = html.escape(pretty)
    for key in ("mode", "fusion", "produced_by", "ranks", "score"):
        text = text.replace(f"&quot;{key}&quot;", f'<b class="k">&quot;{key}&quot;</b>')
    return f"""<!doctype html><title>datasheet search</title><style>
body{{margin:0;background:#0f1d1a;color:#e8efe9;font:20px/1.45 Menlo,monospace}}
header{{padding:22px 32px;background:#0b5d4b;color:#fff;font:600 24px system-ui}}
header small{{display:block;font:16px Menlo,monospace;opacity:.85;margin-top:6px}}
pre{{margin:0;padding:24px 32px;white-space:pre-wrap}} .k{{color:#ffcf66}}</style>
<header>Atlas hybrid search: full text + vector, fused in Atlas<small>GET {html.escape(path)}</small></header>
<pre>{text}</pre>"""


def render_card_page(title: str, body: str, sub: str = "") -> str:
    return f"""<!doctype html><title>{html.escape(title)}</title><style>
body{{margin:0;height:100vh;display:grid;place-content:center;text-align:center;background:#0f1d1a;
color:#e8efe9;font:24px/1.5 system-ui;padding:0 80px}} h1{{font-size:44px;margin:0 0 18px}}
small{{display:block;margin-top:22px;font:17px Menlo,monospace;opacity:.7}}</style>
<h1>{html.escape(title)}</h1><div>{html.escape(body)}</div>{f"<small>{html.escape(sub)}</small>" if sub else ""}"""


def _sign_in(page: Page, code: str | None) -> None:
    gate = page.locator("#access-code")
    try:
        gate.wait_for(state="visible", timeout=10_000)  # Cloud Run cold start
    except PlaywrightTimeout:
        return
    if not code:
        raise SystemExit(
            "record: the site asks for an access code; set GAE_ACCESS_CODE or answer the prompt"
        )
    gate.fill(code)
    page.get_by_role("button", name="Continue").click()
    gate.wait_for(state="hidden", timeout=20_000)
    log("signed in")


def _pick_house(page: Page, how: str) -> None:
    if how == "sample":
        page.get_by_role("button", name="Load Sam's sample (demo)").click()
        page.get_by_role("link", name="Continue").click()
    else:
        print(
            "\n>>> In the browser window: search your postcode, pick the house and press Continue."
            "\n    Nothing is recorded yet; recording starts on the Photos step.",
            file=sys.stderr,
            flush=True,
        )
    page.wait_for_url(re.compile(r"/capture(\?|$)"), timeout=20 * 60_000)
    page.get_by_text("house in").first.wait_for(timeout=15_000)


def record(
    opts: Options, beats: list[Beat], narration: list[float], frames_dir: Path
) -> tuple[list[BeatMarks], Recorder]:
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=not opts.headed)
        except Exception:
            browser = p.chromium.launch(channel="chrome", headless=not opts.headed)
        context = browser.new_context(viewport=VIEWPORT, device_scale_factor=SCALE, locale="en-GB")
        context.add_init_script(CURSOR_JS)
        page = context.new_page()
        page.goto(opts.url)
        _sign_in(page, opts.access_code)
        _pick_house(page, opts.house)
        rec = Recorder(frames_dir)
        director = Director(page, rec, opts)
        director.preload_photos()
        page.evaluate("() => window.scrollTo(0, 0)")
        director.check_privacy("the Photos step before recording")
        page.mouse.move(900, 300)
        rec.attach(page)
        page.wait_for_timeout(600)
        log("recording")
        try:
            for beat, secs in zip(beats, narration, strict=True):
                director.play(beat, secs)
        finally:
            rec.detach()
            browser.close()
        return director.marks, rec
