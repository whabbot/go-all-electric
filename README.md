# Go All-Electric

A photo-and-bill check that tells a homeowner whether a heat pump will actually be cheaper for
them, and what a good installation must look like to get there. Solar and EV charging feed into
one sequenced "go all-electric" plan.

> Your gas bills have already measured your house; we use that to check the installer's maths.

**Sam** owns a 1930s semi with a gas boiler and three installer quotes: 6kW, 9kW and 12kW. Sam has
no idea which is right. A year of gas bills says the house needs about 5kW, so two of those quotes
are oversized.

It advises; you decide. Every figure is a second opinion with a confidence range, to take into the
installer's survey, not a replacement for it.

Built for the Encode London Hackathon (23-25 Oct 2026). All code in this repo was written during
the hackathon; open-source libraries and starter templates are credited below.

## Status

| Piece | State |
| --- | --- |
| Heat-pump maths core (`backend/src/gae/heatpump/`) | Built, unit-tested |
| FastAPI backend with health endpoint | Built |
| React frontend | Placeholder page that calls the backend |
| Gemini photo and bill reading, EPC lookup, degree days, MongoDB Atlas | Planned |
| Quote checker, solar, EV charging, sequenced plan | Planned |

## How the maths works

All of it is pure Python with no network calls, in `backend/src/gae/heatpump/`. Every constant
lives, with its source and date, in [`constants.py`](backend/src/gae/heatpump/constants.py).

1. **Estimate B, measured** (`measured.py`): `HTC (W/K) = E_gas,heating x boiler_efficiency x 1000
   / (degree_days x 24)`, then `P_design = HTC x (21C - design outdoor temp)`, which defaults to
   -2C for London. Summer months set the hot-water and cooking baseline; if there are none, a
   default fraction is used and flagged. The range is about ±20%. Sunny or partly heated homes
   are flagged because their bills read low.
2. **Estimate A, fabric** (`fabric.py`): an installer-style U x A sum plus ventilation, from
   EPC-like inputs. It uses named CIBSE/RdSAP-style defaults, such as 1.5 air changes per hour
   for pre-2000 homes and U=2.8 for double glazing of unknown date.
3. **Cross-check** (`crosscheck.py`): the A/B ratio, plus a ranked list of the likely reasons
   they differ and the inputs behind each one. Typical reasons are a default air change rate,
   pessimistic glazing, missed insulation, or a sunny or part-heated home.
4. **Cost answer** (`costs.py`): gas vs heat pump at the October 2026 price cap (electricity
   26.32p/kWh, gas 7.97p/kWh). Heat pump efficiency (SCOP) falls about 3% per degree of flow
   temperature. The output includes the break-even SCOP and the flow temperature above which the
   heat pump costs more.
5. **Target spec** (`spec.py`): a size range from the measured load and a recommended maximum
   flow temperature of 45C. Radiators are checked using the n=1.3 correction from their Delta-T
   50 ratings. The Boiler Upgrade Scheme grant is £7,500 when replacing gas and £9,000 when
   replacing oil or LPG.

The worked Sam example is in [`backend/tests/test_sam.py`](backend/tests/test_sam.py): bills say
about 4.7kW (3.7-5.7kW), the fabric calc says about 8.7kW, and the target is a 5-7kW unit.

## Setup

You need Python 3.12+ with [uv](https://docs.astral.sh/uv/), and Node 20+ with npm.

```bash
cp .env.example .env        # then fill in the keys you have; .env is git-ignored
```

### Backend

```bash
cd backend
uv sync
uv run uvicorn gae.main:app --reload    # http://127.0.0.1:8000/api/health
uv run pytest                           # tests
uv run ruff check . && uv run ruff format --check .
```

### Frontend

```bash
cd frontend
npm install
npm run dev                              # http://localhost:5173, proxies /api to the backend
npm run build
```

### Secret scan on commit

```bash
uvx pre-commit install      # runs gitleaks and a private-key check before every commit
```

CI (`.github/workflows/ci.yml`) runs on every PR. It runs backend ruff and pytest, then the
frontend lint and build, then a gitleaks scan of the full history.

## Environment variables

| Variable | Used for | Status |
| --- | --- | --- |
| `GEMINI_API_KEY` | Gemini 4 Argon photo and bill reading | Planned |
| `EPC_API_EMAIL` | EPC Open Data API (basic-auth user) | Planned |
| `EPC_API_KEY` | EPC Open Data API (basic-auth key) | Planned |
| `MONGODB_URI` | MongoDB Atlas connection string | Planned |
| `GOOGLE_SOLAR_API_KEY` | Google Solar API roof potential | Planned |

## Secrets

Keys live in `.env` only and are used server-side only. The frontend never receives any API key.
The backend loads keys with pydantic-settings as `SecretStr`, so they print as `**********`. They
are never logged or returned by the API: `/api/health` reports only whether each integration is
configured, as true or false. The browser talks to the backend only through `/api`. Never put a key
in a `VITE_*` variable, because Vite bundles those into the browser build.

`.gitignore` excludes `.env*` (except `.env.example`). It also excludes `private/` and
`demo-data/`, which is where real photos, bills and addresses must go. Never commit them.

## Privacy and honesty

- Photos are for reading data plates, radiators and fuse cutouts. Faces, number plates and street
  views are not needed, and the photo pipeline (planned) will be told to ignore them and not store
  them.
- Answers are ranges with stated caveats, never a single confident number. Where the two estimates
  disagree, the app says why instead of averaging them.
- When data is missing (no summer bills, no efficiency on the data plate), the maths falls back to
  a named default, widens the range and flags it.

## Models and data sources

| Source | Use | Status |
| --- | --- | --- |
| Gemini 4 Argon (`gemini-4-argon`) via the Interactions API, `google-genai>=2.3.0` | Read boiler data plates, radiators, fuse cutouts and gas bills from photos | Planned (dependency declared) |
| [EPC Open Data API](https://epc.opendatacommunities.org/) (DLUHC) | Floor area, property type, age, walls, glazing, heating for an address | Planned |
| [Open-Meteo](https://open-meteo.com/) historical weather | Heating degree days for the bill period | Planned |
| [Google Solar API](https://developers.google.com/maps/documentation/solar) / [PVGIS](https://joint-research-centre.ec.europa.eu/pvgis-online-tool_en) | Roof solar potential | Planned |
| MongoDB Atlas | Core data store (homes, estimates, quotes) | Planned (dependency declared) |
| Ofgem price cap, Oct-Dec 2026 | Unit rates in the cost answer | Built (constants) |
| CIBSE Guide A, RdSAP defaults, MCS guidance, BS EN 442 | Fabric defaults, design temperatures, radiator exponent | Built (constants) |

## Agent skills

`.agents/skills/gemini-api-dev` holds Google's Gemini API skill for coding agents. It was installed
with `npx skills add google-gemini/gemini-skills --skill gemini-api-dev` and is symlinked for
Claude Code under `.claude/skills/`.

## Licence

[MIT](LICENSE).
