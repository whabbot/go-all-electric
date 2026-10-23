"""Opt-in live POST through the real FastAPI route; only sample page images are sent.

Run with the backend environment plus pymupdf (see README). Credentials and raw responses
are never printed. Datasheet checks use the real public seed without contacting Atlas.
"""

from pathlib import Path

import pymupdf
from fastapi.testclient import TestClient
from gae.db.seed import load_seed
from gae.gemini.datasheets import InMemoryDatasheetLookup
from gae.gemini.router import get_datasheets
from gae.main import app
from gae.settings import Settings, get_settings


def main() -> int:
    settings = Settings(_env_file=Path.home() / ".config/go-all-electric/.env")
    if not settings.gemini_api_key:
        print("SKIP: GEMINI_API_KEY is not configured.")
        return 0
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_datasheets] = lambda: InMemoryDatasheetLookup(load_seed())
    files = []
    indices = []
    names = []
    for index, letter in enumerate("abc"):
        name = f"sample-quote-{letter}.pdf"
        with pymupdf.open(Path(__file__).parent / "quotes" / name) as document:
            for page in document:
                image = page.get_pixmap(dpi=120).tobytes("jpeg")
                files.append(("quotes", (f"{letter}-{page.number}.jpg", image, "image/jpeg")))
                indices.append(str(index))
                names.append(name)
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.post(
                "/api/quotes/check",
                files=files,
                data={
                    "quote_index": indices,
                    "quote_name": names,
                    "size_low_kw": "5",
                    "size_high_kw": "7",
                    "design_load_kw": "4.7",
                },
            )
        if response.status_code != 200:
            print(f"FAIL: /api/quotes/check returned HTTP {response.status_code}; body withheld.")
            return 1
        results = response.json()
        if len(results) != 3 or any(r["verified"]["reading"] is None for r in results):
            print("FAIL: expected three readable quotes.")
            return 1
        for result in results:
            severities = [f["severity"] for f in result["flags"]]
            print(f"{result['filename']}: {result['verified']['status']}; flags={severities}")
        a, _, c = results
        checks = {
            "A has no red flags": not any(f["severity"] == "red" for f in a["flags"]),
            "all models matched datasheets": all(r["verified"]["datasheet_id"] for r in results),
            "outputs read as 6/9/12 kW": [r["quoted_kw"] for r in results] == [6, 9, 12],
            "C oversized red": any(
                f["severity"] == "red" and "oversized" in f["message"] for f in c["flags"]
            ),
            "C 55C flow amber": any(
                f["severity"] == "amber" and "55" in f["message"] for f in c["flags"]
            ),
            "C buffer amber": any(
                f["severity"] == "amber" and "Buffer tank" in f["message"] for f in c["flags"]
            ),
            "C undeducted grant red": any(
                f["severity"] == "red" and "Grant not deducted" in f["message"] for f in c["flags"]
            ),
        }
        for label, passed in checks.items():
            print(f"{'PASS' if passed else 'FAIL'}: {label}")
        return 0 if all(checks.values()) else 1
    except Exception:
        print("FAIL: live check failed; exception detail withheld to protect credentials.")
        return 1
    finally:
        app.dependency_overrides.clear()


if __name__ == "__main__":
    raise SystemExit(main())
