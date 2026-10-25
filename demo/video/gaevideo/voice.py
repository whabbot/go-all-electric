"""Narration: Gemini TTS (gemini-3.8-flash-tts), or macOS `say` when no key is configured.

One WAV per beat, leading/trailing silence trimmed, cached by (engine, voice, style, text) so
editing one line only re-voices that line.
"""

import base64
import hashlib
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

GEMINI_TTS_MODEL = "gemini-3.8-flash-tts"
DEFAULT_GEMINI_VOICE = "Charon"
DEFAULT_SAY_VOICE = "Daniel"
KEY_FILE = Path(os.environ.get("GAE_ENV_FILE", "~/.config/go-all-electric/.env")).expanduser()


def gemini_key() -> str | None:
    """GEMINI_API_KEY from the environment or the private keys file. Never printed."""
    if os.environ.get("GEMINI_API_KEY"):
        return os.environ["GEMINI_API_KEY"]
    if not KEY_FILE.is_file():
        return None
    for line in KEY_FILE.read_text().splitlines():
        line = line.strip().removeprefix("export ")
        if line.startswith("GEMINI_API_KEY="):
            return line.split("=", 1)[1].strip().strip("'\"") or None
    return None


def duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(out.stdout.strip())


# Trim leading/trailing silence, then even out loudness to about -16 LUFS (web video level).
_FILTER = (
    "silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.05,areverse,"
    "silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.15,areverse,"
    "loudnorm=I=-16:TP=-1.5:LRA=11"
)
_FILTER_VERSION = 2  # part of the cache key: bump when _FILTER changes


def _normalise(src: Path, dst: Path) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-i",
            str(src),
            "-af",
            _FILTER,
            "-ar",
            "48000",
            "-ac",
            "1",
            str(dst),
        ],
        check=True,
    )


class Voice:
    def __init__(self, engine: str, voice: str | None, style: str, cache: Path):
        self.style = style
        self.cache = cache
        cache.mkdir(parents=True, exist_ok=True)
        if engine == "auto":
            engine = "gemini" if gemini_key() else "say"
        if engine == "gemini" and not gemini_key():
            raise SystemExit(
                "voice: no GEMINI_API_KEY (environment or keys file); use --voice-engine say"
            )
        if engine == "say" and not shutil.which("say"):
            raise SystemExit("voice: macOS `say` is not available")
        self.engine = engine
        self.voice = voice or (DEFAULT_GEMINI_VOICE if engine == "gemini" else DEFAULT_SAY_VOICE)
        self._client = None

    def label(self) -> str:
        return (
            f"{GEMINI_TTS_MODEL} ({self.voice})"
            if self.engine == "gemini"
            else f"macOS say ({self.voice})"
        )

    def _path(self, text: str) -> Path:
        key = f"{_FILTER_VERSION}|{self.engine}|{self.voice}|{self.style}|{text}"
        h = hashlib.sha256(key.encode()).hexdigest()[:16]
        return self.cache / f"{self.engine}-{h}.wav"

    def _gemini(self, text: str, raw: Path) -> None:
        if self._client is None:
            from google import genai

            self._client = genai.Client(api_key=gemini_key())
        content = {"type": "text", "text": text}
        if self.style:
            content["annotations"] = [{"type": "speech_metadata", "style": self.style}]
        result = self._client.interactions.create(
            model=GEMINI_TTS_MODEL,
            input=[{"type": "user_input", "content": [content]}],
            response_format={"type": "audio"},
            generation_config={"speech_config": [{"voice": self.voice}]},
        )
        if not result.output_audio:
            raise RuntimeError("Gemini TTS returned no audio")
        raw.write_bytes(base64.b64decode(result.output_audio.data))

    def _say(self, text: str, raw: Path) -> None:
        aiff = raw.with_suffix(".aiff")
        subprocess.run(["say", "-v", self.voice, "-r", "185", "-o", str(aiff), text], check=True)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(aiff), str(raw)], check=True)
        aiff.unlink()

    def speak(self, text: str) -> Path:
        out = self._path(text)
        if out.exists():
            return out
        raw = out.with_suffix(".raw.wav")
        if self.engine == "say":
            self._say(text, raw)
        else:
            # Retry rather than mix voices; a lasting failure says how to switch engine.
            for attempt in range(3):
                try:
                    self._gemini(text, raw)
                    break
                except Exception as e:
                    print(
                        f"voice: Gemini TTS attempt {attempt + 1} failed ({type(e).__name__})",
                        file=sys.stderr,
                    )
                    if attempt == 2:
                        raise SystemExit(
                            "voice: Gemini TTS keeps failing; re-run with --voice-engine say"
                        ) from None
                    time.sleep(2 + 4 * attempt)
        _normalise(raw, out)
        raw.unlink()
        return out

    def speak_all(self, texts: list[str]) -> list[tuple[Path, float]]:
        with ThreadPoolExecutor(max_workers=4) as pool:
            paths = list(pool.map(self.speak, texts))
        return [(p, duration(p)) for p in paths]
