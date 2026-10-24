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
| React frontend | Mobile-first demo UI on the live API; offline mocks with `VITE_USE_MOCKS=true` |
| End-to-end analysis (`backend/src/gae/survey/`) | Built: EPC, photos, bill and weather to the maths core, streamed live log, saved to Atlas |
| EPC lookup and exact-period heating degree days | Built, mocked HTTP tests |
| MongoDB Atlas persistence and datasheet retrieval | Built; managed embeddings require Atlas setup |
| Gemini photo checks, verified extraction and one-context review | Built, fake-client tests plus a live smoke test |
| Quote checker (flags in code from verified quote readings) | Built |
| Solar, EV charging, sequenced plan | Built (`gae/plan/`, Plan screen) |
| Your pack: installer emails drafted by Gemini 4 Argon, number-checked, template fallback | Built (`gae/pack/`, Pack screen) |

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

You need Python 3.14+ with [uv](https://docs.astral.sh/uv/), and Node 20+ with npm.

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
cp .env.example .env                     # VITE_USE_MOCKS=true uses Sam's worked example offline
npm install
npm run dev                              # http://localhost:5173, proxies /api to the backend
npm run build
```

With `VITE_USE_MOCKS=true` (default in `.env.example`), the UI runs the full demo flow without a
backend, labelled "offline demo data"; the production build and CI need no backend. Set
`VITE_USE_MOCKS=false` to use the live API; the browser still calls only `/api` via the Vite proxy
(no API keys in the frontend).

### Run the demo locally

```bash
cp .env.example .env                     # GEMINI_API_KEY, EPC_API_TOKEN, MONGODB_URI (optional)

cd backend
uv sync
uv run python -m gae.db.seed             # once: public datasheet library into Atlas (safe to repeat)
uv run python -m gae.db.indexes          # once: Search + Vector Search indexes (safe to repeat)
uv run uvicorn gae.main:app --port 8000  # http://127.0.0.1:8000/api/health shows what is configured

cd ../frontend                           # second terminal
npm install
VITE_USE_MOCKS=false npm run dev         # http://localhost:5173
```

Then: enter a postcode and pick a **house** (flats are refused by design), add the photos you have
(boiler plate, radiator, fuse cutout and gas bill; the outdoor spot is optional), redact each one,
and press **Run estimates**. Without `MONGODB_URI` everything still runs: datasheets come from the
seed file in memory and the survey is simply not saved.

What happens on **Run estimates** (`POST /api/analysis`, multipart: `certificate_id` plus one file
per photo kind, all optional):

1. The EPC fetch and every photo/bill extraction start together; each extraction is its own Gemini
   verification loop (read, check in code, re-read once on failure, give up honestly).
2. The bill's exact dates and the postcode centroid give heating degree days (Open-Meteo), then
   Estimate B. No bill, or a bill that isn't a full 12 months, means no Estimate B: the screen says
   what to provide, and the cross-check says it can't compare.
3. The maths core runs: fabric (A), measured (B), cross-check, costs by flow temperature, target spec.
4. The survey is saved to Atlas with the postcode district only.

The response streams newline-delimited JSON (`step`, `log`, then one `result` or `error`), so the
verification log appears as it happens, including any failed check and its re-read. After the
estimates are on screen, **Ask Gemini to review everything** calls `POST /api/analysis/review`
(the bundle, readings and the same redacted files; 1-2 minutes at high thinking). Checked quotes on
the Quotes screen are sized against the bundle's target range and measured design load.

On **Your pack**, **Draft with Gemini** calls `POST /api/pack/installer-drafts` with numbers only:
the target range, flow temperature, measured load, fuse rating, and each checked quote's verified
fields, flags and questions by label ("Quote C (12 kW)"). The request has no field for an address,
name, account or meter number, and rejects unknown fields and postcode-like text. Per quote, code
picks two or three right-sized heat pumps from the datasheet library, Gemini 4 Argon (medium
thinking, about 6-10 seconds, quotes in parallel) writes the email, and the review's number check
removes any sentence with a number we did not supply. If more than a third is removed, the email
names no library model, or Gemini fails, the deterministic template is returned instead. Nothing is
sent: the homeowner reviews, edits and copies the draft.

### Secret scan on commit

```bash
uvx pre-commit install      # runs gitleaks and a private-key check before every commit
```

CI (`.github/workflows/ci.yml`) runs on every PR. It runs backend ruff and pytest, then the
frontend lint and build, then a gitleaks scan of the full history.

## Environment variables

| Variable | Used for | Status |
| --- | --- | --- |
| `VITE_USE_MOCKS` | Frontend: mock Sam demo vs live `/api` (never put secrets in `VITE_*`) | Built |
| `GEMINI_API_KEY` | Gemini photo checks, bill/quote reading and the review | Built |
| `GEMINI_LEAD_MODEL`, `GEMINI_FAST_MODEL` | Optional model ids (defaults `gemini-4-argon`, `gemini-3.8-flash`); not secrets | Built |
| `EPC_API_TOKEN` | GOV.UK EPC replacement API bearer token, issued after GOV.UK One Login | Required for EPC lookup |
| `EPC_API_EMAIL`, `EPC_API_KEY` | Retained legacy configuration; retired API Basic auth is no longer used | Deprecated |
| `MONGODB_URI` | Server-side Atlas connection string; database `go_all_electric` | Built |
| `GOOGLE_SOLAR_API_KEY` | Google Solar API roof potential | Planned |

### Open-data endpoints

Create a GOV.UK One Login account via the [EPC API guidance](https://get-energy-performance-data.communities.gov.uk/guidance/energy-certificate-data-apis),
then set `EPC_API_TOKEN` to the bearer token on your account page. The legacy EPC service retired
in May 2026; old email/key credentials are not a substitute. Weather needs no credentials.

- `GET /api/epc/search?postcode=...` returns matching addresses and their latest certificate IDs.
- `GET /api/epc/{certificate_id}` returns an allowlisted raw summary, mapped fabric inputs,
  field confidence/defaults and a fabric estimate (or a clear reason it cannot be calculated).
- `GET /api/weather/degree-days?postcode=...&start=YYYY-MM-DD&end=YYYY-MM-DD` returns degree days,
  inclusive coverage, missing-day count and the explicitly low-confidence -2C London design default.

The bill adapter `gae.opendata.bill.measured_from_bill` accepts any complete 12-month window,
including leap years, using injected weather access; missing days return `couldnt_tell`, never
substituted weather. `measured_from_degree_days` is the pure calculation counterpart.
See the [explicit EPC mapping table and integration contract](backend/src/gae/opendata/MAPPING.md)
for defaults, unsupported flats, monthly-bill requirements and weather uncertainty. Display its
field caveats alongside the fabric result. These clients do not persist addresses or coordinates;
responses disable caching. Disable query-string logging in deployment to keep postcodes private.

### Gemini endpoints

Set `GEMINI_API_KEY` (from [Google AI Studio](https://aistudio.google.com/apikey); Gemini 4 Argon
needs a paid-tier key). Uploads are multipart, held in memory for the request and never stored.

- `POST /api/photos/check` (`kind`, `file`) is the instant check on upload: what the photo shows,
  whether it is legible, key fields already visible, a retake hint, and a face/number-plate warning.
- `POST /api/photos/extract` (`kind`, `file`) runs the verification loop and returns a typed
  reading, its status (`verified`, `verified_with_warnings` or `couldnt_tell` with what to
  photograph instead) and the step-by-step verification log for the UI.
- `POST /api/radiators/video` (`file`, optional `design_load_kw`) strips container metadata,
  watches a radiator walkthrough video on `gemini-4-argon` (`thinking_level=high`), checks count,
  de-duplication and radiator dimensions/types in code, re-asks once on failure, checks upsizing at
  45C flow, and turns any still-uncertain radiator into a `"couldn't tell: photograph the radiator
  seen at 0:14"` request.
- `POST /api/quotes/check` (`quotes` page images, parallel `quote_index` and `quote_name` per
  page so multi-page PDFs stay one quote; optional `size_low_kw`, `size_high_kw`, `design_load_kw`
  from the maths core) reads each quote through the same loop and flags it in code:
  oversized, high design flow, buffer tank, grant not deducted, kW not matching the datasheet.
- `POST /api/analysis` (accepts an optional `radiator_video` alongside or instead of radiator
  photos) and `POST /api/analysis/review` run the whole survey; see
  [Run the demo locally](#run-the-demo-locally).
- `POST /api/review` (JSON) sends photos, bill, EPC record, full matched datasheets, every quote and
  the maths-core outputs to one Gemini 4 Argon interaction, then removes any statement whose
  numbers do not trace back to those inputs.

`kind` is one of `boiler_plate`, `radiators`, `fuse_cutout`, `outdoor_space`, `gas_bill`.

## Secrets

Keys live in `.env` for local development and Secret Manager for Cloud Run, and are used
server-side only. The frontend never receives any API key.
The backend loads keys with pydantic-settings as `SecretStr`, so they print as `**********`. They
are never logged or returned by the API: `/api/health` reports only whether each integration is
configured, as true or false. The browser talks to the backend only through `/api`. Never put a key
in a `VITE_*` variable, because Vite bundles those into the browser build.

`.gitignore` excludes `.env*` (except `.env.example`). It also excludes `private/` and
`demo-data/`, which is where real photos, bills and addresses must go. Never commit them.

## Privacy and honesty

- **On your device before upload:** every photo and bill image is re-encoded in the browser (canvas
  → JPEG) so EXIF, GPS, device and timestamp metadata never leave your phone. You then crop and
  drag opaque black boxes over anything identifying (house numbers, street signs, faces, cars, names,
  post, account or meter numbers). Installer quote PDFs are rendered to images in the browser
  (pdf.js) and go through the same redaction step per page; the server receives redacted JPEGs, not
  the original PDF. Nothing is sent until you confirm the labelled preview (“exactly what will be
  sent”).
- **What reaches Gemini:** only the redacted JPEG bytes from that step, over HTTPS to our backend,
  which strips any remaining image metadata in memory (Pillow) before the paid Gemini API call.
  Calls use `store=False`, so Google does not retain your uploads as stored interactions.
- **Radiator walkthrough video privacy:** the Capture screen warns plainly that video is not
  covered up like photos: film radiators only, close, with no windows, people or house numbers.
  Videos are capped at 100 MB and 90 seconds. Before any Gemini call, the backend strips all
  container metadata (GPS/location atoms, device tags, creation/modification timestamps) server-side
  in memory for MP4/MOV, or via a private temporary directory deleted in a `finally` block when
  remuxing WebM. Inline video (`store=False`) is preferred; when the Files API is required for
  larger videos, the uploaded file is deleted immediately after the Gemini call in a `finally`
  block. Videos are never written to MongoDB Atlas or logs.
- **What we store:** no upload files, no raw photos, no radiator videos, and no bill or quote documents. The API keeps
  uploads in RAM for the request only. A saved survey holds the postcode district (outward code,
  e.g. `HA8`) as its only location, plus extracted readings, the maths bundle and the verification
  log. Never an address, full postcode, UPRN or certificate number: the survey model rejects them.
- **Where the house is stays private:** once you pick your house, every screen shows only "house in
  HA8" (the district). Gemini never receives an address: the review gets an allowlist of EPC building
  fields (type, age band, floor area, wall/roof/floor/window/heating descriptions, ratings), with
  any address, postcode, UPRN or certificate key stripped, and a test asserts none reaches the
  request. Quotes are labelled "Quote A", "Quote B", not by file name.
- Photos are for reading data plates, radiators and fuse cutouts. Gemini is told never to transcribe
  people, plates, names, addresses or meter numbers; the instant check warns when identifying
  detail may still be visible and asks you to cover it and resend.
- Every Gemini reading is checked in code (bill period about a year, kWh plausible, plate model
  in the datasheet library and within its catalogue output, quote line items add up). A failed
  check gets one more careful look; if that fails too the answer is "couldn't tell" plus what to
  photograph instead, never a guess.
- The review explains; it does not calculate. Every number it writes must match the maths core or
  the user's own documents, otherwise the statement is removed and listed.
- Answers are ranges with stated caveats, never a single confident number. Where the two estimates
  disagree, the app says why instead of averaging them.
- When data is missing (no summer bills, no efficiency on the data plate), the maths falls back to
  a named default, widens the range and flags it.

## Models and data sources

| Source | Use | Status |
| --- | --- | --- |
| Gemini 4 Argon (`gemini-4-argon`) via the Interactions API, `google-genai>=2.3.0` | Reads gas bills and installer quotes (`thinking_level` medium); watches radiator walkthrough videos (`thinking_level` high, verified in code with one re-read and photo requests for uncertain radiators); every re-read after a failed code check (high); one-context review of all evidence (high) | Built |
| Gemini 3.8 Flash (`gemini-3.8-flash`) via the Interactions API | Instant photo check on upload (`thinking_level` low, about 3-4 s); first read of data plates, radiators, fuse cutouts and outdoor space (medium) | Built |
| [Get energy performance of buildings data](https://get-energy-performance-data.communities.gov.uk/guidance/energy-certificate-data-apis) (MHCLG, England/Wales) | Latest EPC per matching address, floor area, dwelling form, age band, fabric and heating descriptions | Built; 2026 replacement API, bearer auth |
| [postcodes.io](https://postcodes.io/docs/api/lookup-postcode/) | Postcode centroid for weather requests; no exact home coordinates stored | Built; no key |
| [Open-Meteo](https://open-meteo.com/en/docs/historical-weather-api) historical reanalysis | Daily mean temperatures at postcode centroid; heating degree days at 15.5C base for exact inclusive bill dates | Built; no key; attribution Open-Meteo, weather data CC BY 4.0 |
| [postcodes.io](https://postcodes.io/docs/api/outward-code/) outward code | Postcode-district centroid for PVGIS (never a full postcode) | Built; no key |
| [PVGIS](https://joint-research-centre.ec.europa.eu/pvgis-online-tool_en) PVcalc v5.2 | Typical annual yield for a named default array at the district centroid | Built; no key |
| [Google Solar API](https://developers.google.com/maps/documentation/solar) | Site-specific roof modelling | Out of scope for hackathon demo |
| MongoDB Atlas | Core survey store, fuzzy Search, Vector Search, hybrid datasheet matching | Built (`gae/db`) |
| Voyage `voyage-4-lite` through Atlas Automated Embedding | Managed embeddings of public manufacturer datasheet text and model queries | Built; requires supported Atlas cluster and queryable index |
| Manufacturer UK product pages and technical brochures | 15 heat pump / gas boiler variants; per-entry source URLs in `gae/db/datasheets.json` | Curated seed; unverified values are null |
| Ofgem price cap, Oct-Dec 2026 | Unit rates in the cost answer | Built (constants) |
| CIBSE Guide A, RdSAP defaults, MCS guidance, BS EN 442 | Fabric defaults, design temperatures, radiator exponent | Built (constants) |

## How we use MongoDB Atlas

Atlas is the core backend store. `surveys` holds one document per analysis with the postcode
district only (never an address), EPC building snapshot, extracted readings with confidence, both
estimates, cross-check, cost, target spec, quote flags and verification log. UUIDs identify
surveys; creation/update times are server generated. `datasheets` holds 15 public manufacturer variants from Vaillant,
Mitsubishi Electric, Daikin, Samsung, Worcester Bosch, Baxi and Ideal.

- **Atlas Search:** `datasheets_text` indexes make, model and curated text with fuzzy matching,
  useful for OCR mistakes such as “Vailant”.
- **Atlas Vector Search:** `datasheets_semantic` searches the public datasheet text semantically,
  useful when a plate or quote uses a different description.
- **Automated Embedding / Voyage AI:** `autoEmbed`, model `voyage-4-lite`, generates document
  and query embeddings inside Atlas. No separate Voyage key is needed. Only public product
  facts and model search text enter the embedding model; survey documents are never indexed.
- **Native Atlas Hybrid Search:** `$rankFusion` combines `$search` and `$vectorSearch` inside
  MongoDB using reciprocal-rank fusion with equal channel weights. `scoreDetails` metadata
  provides the contributing channels and ranks for each result. Responses identify the path as
  `fusion: native_rank_fusion`. This native stage was verified against Atlas Local.
  Clusters lacking the native stage fall back to application RRF (`sum(1 / (60 + rank))`),
  labelled `fusion: application_rrf` with a warning. A known unavailable semantic index returns
  an explicit full-text-only warning and `fusion: none`; other driver failures return a generic
  503. Scores rank candidates; they are not identification confidence.

Setup from `backend/`:

1. Create an Atlas cluster supporting Search, Vector Search and the Automated Embedding preview;
   use a least-privilege database user and restrict network access. Enable storage auto-scaling
   on dedicated clusters as required by Automated Embedding. Set server-only `MONGODB_URI`.
2. Run `uv run python -m gae.db.seed` (upserts stable IDs; safe to repeat).
3. Run `uv run python -m gae.db.indexes` (creates or updates definitions; safe to repeat).
   Wait for both indexes to show `queryable: true` in Atlas before demoing hybrid search.
4. Start the backend, then call `GET /api/datasheets/search?q=Vaillant%20aroTHERM`.
   `POST /api/surveys`, `GET /api/surveys`, and `GET`, `PUT`, `DELETE /api/surveys/{id}`
   persist, list, replace and erase surveys. `PUT` replaces editable fields, including defaults.

The data layer uses synchronous PyMongo in FastAPI's worker threadpool. Its own `DatasheetLookup`
Protocol provides `find_by_make_model(text)`, `get_full_datasheet_text(id)` (the full curated
record text, not a downloaded PDF), and `search_by_spec(min_kw=..., max_kw=..., kind=...)`.
An adapter can wire these methods into the Gemini worker once its interface lands. Capacity
filters use the manufacturer's nominal class; combi names usually denote hot-water capacity,
so central-heating min/max are stored separately. SCOP is a published comparison under stated
conditions, not a running-cost guarantee; nulls must never become invented specifications.

This is a localhost, single-user hackathon API: survey routes do not yet have user authentication
or tenant isolation. Keep it bound to loopback or behind a trusted access proxy, use synthetic
surveys for shared demos, and add authentication before exposing real homeowner records.
Survey validation rejects image/raw-document fields, data-image URLs, unsafe keys and oversized
payloads. It cannot identify personal content inside free text; extraction must discard faces,
plates and raw photos upstream. No source image is stored by this package. Delete a survey when
it is no longer needed. No information is sent to installers or network operators.

Unit tests mock the driver and use no network or keys. The optional integration test uses real
Atlas Local Search, Vector Search and native `$rankFusion` with a tiny synthetic-vector fixture, a unique temporary
collection, and cleanup; it does **not** validate managed Voyage inference. Run it explicitly:

```bash
docker run --detach --rm --name gae-atlas-test -p 127.0.0.1:27028:27017 mongodb/mongodb-atlas-local:latest
ATLAS_LOCAL_URI='mongodb://127.0.0.1:27028/?directConnection=true' uv run pytest -m atlas_local -o addopts='' tests/test_db_atlas_local.py
docker stop gae-atlas-test
```

Index syntax and model availability were checked against the official
[Automated Embedding documentation](https://www.mongodb.com/docs/vector-search/crud-embeddings/automated-embedding/),
[Atlas Search text operator](https://www.mongodb.com/docs/atlas/atlas-search/text/), and
[RRF documentation](https://www.mongodb.com/docs/manual/reference/operator/aggregation/rankfusion/).
Automated Embedding is a preview capability; unsupported clusters need a compatible deployment
before semantic queries can work. Optional Voyage reranking is not enabled for this small library.

## Agent skills

`.agents/skills/gemini-api-dev` holds Google's Gemini API skill for coding agents. It was installed
with `npx skills add google-gemini/gemini-skills --skill gemini-api-dev` and is symlinked for
Claude Code under `.claude/skills/`.

## Licence

[MIT](LICENSE).


## Deploy to Cloud Run

One Python 3.14 container builds the real API frontend (`VITE_USE_MOCKS=false`) and
serves it with FastAPI on `$PORT` (default 8080). `/api` and the app share an origin;
refreshing `/capture`, `/quotes`, `/pack` or `/plan` works. No key is used at build time
or placed in a `VITE_*` variable. `.dockerignore` and `.gcloudignore` exclude private
inputs, env files, dependencies and test caches from the image and source upload.

Infrastructure lives in `deploy/tofu/` and uses OpenTofu with local state. Helm
manages Kubernetes; Cloud Run is managed directly through the pinned Google provider.
Image builds run separately through `deploy/build.sh`.

Before deploying:

1. Install OpenTofu 1.13.2 and Google Cloud CLI. Run `gcloud auth login` for builds,
   then `gcloud auth application-default login` for OpenTofu (alternatively supply
   `GOOGLE_OAUTH_ACCESS_TOKEN` in the environment). Select a billed project; examples
   below use `go-all-electric-demo` in `europe-west2`.
   The deployer needs permissions to enable APIs, manage networking and external IPs,
   service accounts, project and secret IAM, Artifact Registry, Logging exclusions,
   Cloud Build and Cloud Run, plus permission to act as `gae-build` and `gae-runtime`.
   Source upload also requires Cloud Storage access. The build account receives
   `roles/run.builder`; runtime access is restricted to the five named secrets.
2. Open [Secret Manager](https://console.cloud.google.com/security/secret-manager?project=go-all-electric-demo)
   in that project and enable its API if prompted. For each exact name `GEMINI_API_KEY`,
   `MONGODB_URI`, `EPC_API_TOKEN`, `ACCESS_CODE_HASH` and `SESSION_SECRET`, click
   **Create secret**, enter the name, paste its value into **Secret value**, then click
   **Create**. Keep an enabled version for each secret. The last two never hold the code:
   - `ACCESS_CODE_HASH`: choose a demo access code and share it privately with judges.
     In `backend/`, run `uv run python -m gae.security hash-access-code | pbcopy`, type
     the code twice (it is not echoed), then paste the copied `scrypt$...` line.
   - `SESSION_SECRET`: run `openssl rand -base64 48 | tr -d '\n' | pbcopy` and paste it.
     It signs session cookies; replacing it signs every visitor out.
   OpenTofu reads secret metadata only: it never reads, creates or uploads secret values.
   A missing or inaccessible secret fails the plan with its name and the API error;
   create it in the console or correct metadata permissions before continuing.
3. Copy `deploy/tofu/example.tfvars` to `deploy/tofu/terraform.tfvars` and adjust the
   project if needed. Private variable files, state and working data are ignored by Git.
   Keep local state and its backups safe: subsequent plans and cleanup need that state.
   There is no remote backend. Run commands below from the repository root.

Deploy in three steps, reviewing each plan before applying it:

1. **Bootstrap infrastructure without a service** (`image = null`):

   ```sh
   tofu -chdir=deploy/tofu init
   tofu -chdir=deploy/tofu plan -out=bootstrap.plan
   tofu -chdir=deploy/tofu apply bootstrap.plan
   ```

   This enables APIs and creates the service accounts, Docker repository, secret IAM,
   request-log exclusion, and static egress network: `gae-network`, `gae-egress`
   (`10.42.0.0/24`), `gae-router`, `gae-egress-ip` and `gae-nat`. No default network is
   required. Add exactly the output `egress_ip` as a **/32** in MongoDB Atlas network
   access before deploying the service. Do not allow `0.0.0.0/0`.
2. **Build a committed source tree**, using the dedicated build account:

   ```sh
   GOOGLE_CLOUD_PROJECT=go-all-electric-demo GOOGLE_CLOUD_REGION=europe-west2 ./deploy/build.sh
   ```

   The helper submits the root Dockerfile to Cloud Build and prints an Artifact Registry
   image reference tagged with the full Git commit SHA. It handles no secrets. It
   refuses uncommitted changes so the tag identifies the source. Copy the printed
   reference for the next step.
3. **Deploy that image**:

   ```sh
   tofu -chdir=deploy/tofu plan -var 'image=<printed-image-reference>' -out=deploy.plan
   tofu -chdir=deploy/tofu apply deploy.plan
   ```

   Save the same reference as `image` in your private `terraform.tfvars` immediately
   afterwards. Leaving it null on a later apply would remove the service. For each
   update, build a new commit and repeat this step with its reference.

The service URL is an output after deployment. Cloud Run uses 0–2 instances, 2 GiB
memory, one CPU, concurrency 8, and a 900-second timeout. All outbound traffic uses
Direct VPC egress and Cloud NAT with the single reserved IP. Public invocation is
enabled; the access-code session protects every `/api/*` route except `/api/health` and
the `/api/session` sign-in.
Secret references use `latest`; manage secret versions in the console and deploy a new
revision to pick up rotations in environment variables. Do not run with shell tracing.

Cloud NAT and reserved IPv4 addresses incur charges. To clean up, review
`tofu -chdir=deploy/tofu plan -destroy`, then run `tofu -chdir=deploy/tofu destroy`
using the same local state and variables. This removes the service and managed
infrastructure, but retains the console-managed secrets and leaves APIs enabled.
Remove the Atlas **/32 entry by hand**. Cloud Build source staging objects and build
history are outside OpenTofu state; remove them separately if needed.

The first visit shows **Enter access code**. The server checks it against the salted
scrypt hash in `ACCESS_CODE_HASH` and replies with a signed `gae_session` cookie
(`HttpOnly`, `Secure`, `SameSite=Strict`, `Path=/api`) that expires after 12 hours
(`SESSION_TTL_SECONDS`). The browser never stores the code, and old builds' stored copy
is deleted on load. Changing the code or `SESSION_SECRET` signs everyone out. Each IP may
make 10 wrong attempts per 15 minutes (`SESSION_ATTEMPTS_PER_IP`,
`SESSION_ATTEMPT_WINDOW_SECONDS`) before sign-in returns 429. When `ACCESS_CODE_HASH` is
unset, local development retains its existing open behavior. The app refuses to start if
the hash is malformed, `SESSION_SECRET` is missing or under 32 bytes, or the retired
`ACCESS_CODE` is still set.

To upgrade a deployment that used the plaintext `ACCESS_CODE` secret: create
`ACCESS_CODE_HASH` and `SESSION_SECRET` in the console as above, then build a new commit
and run the **Deploy that image** plan and apply. Once the new revision accepts the code,
delete the old `ACCESS_CODE` secret in the console.

Cloud Run deployments default to 300 Gemini POST requests per IP per 3600 seconds,
so judges and visitors sharing the venue Wi-Fi have a larger shared allowance. Set
`gemini_requests_per_ip` (default 300) and `gemini_limit_window_seconds` (default 3600)
in your private `terraform.tfvars`, then review `tofu plan` and apply the change. These
set the runtime `GEMINI_REQUESTS_PER_IP` and `GEMINI_LIMIT_WINDOW_SECONDS` variables.

Local development with a code set defaults to 30 requests per IP per 3600 seconds.
Both settings also apply when supplied directly to the application
(`GEMINI_REQUESTS_PER_IP=0` disables the limit). A 429 response explains the limit in the UI
and supplies `Retry-After`. Signed-out requests do not consume the allowance.

This small in-memory limiter is per container and resets on restart; two instances can
provide up to two allowances. People sharing Wi-Fi also share an IP allowance. It uses
the last `X-Forwarded-For` address for the direct Cloud Run URL, ignoring supplied prefixes.
Revisit trusted proxy handling if adding another proxy or load balancer. It is a demo
credit guard, not a distributed billing cap.

The container disables uvicorn access logs and HTTP client INFO logs so application
logs do not record query strings or postcodes. Cloud Run's **platform request logs** are
separate and include request URLs. OpenTofu manages an exclusion scoped to
this service's `run.googleapis.com/requests` log in the `_Default` sink before deploying;
application logs remain available, but stored request-level traffic diagnostics do not.
If the project has additional logging sinks, apply the equivalent exclusion there too.
Do not enable HTTP debug logging. Photos remain request data and are not persisted by
this deployment; uploads are never included in the image.

### Local container and Android check

```sh
docker build -t go-all-electric .
docker run --rm -p 8080:8080 \
  --env-file "$HOME/.config/go-all-electric/.env" go-all-electric
```

Ensure that env file includes `ACCESS_CODE_HASH` and `SESSION_SECRET` for gated
validation. Chrome accepts the `Secure` cookie on `http://localhost`; for another
browser over plain http, add `SESSION_COOKIE_SECURE=false` (refused under Cloud Run).
Never put a code or API key on a command line or commit an env file. Use SAMPLE
inputs for verification. Check wrong-code refusal, EPC search and a photo check at
`http://localhost:8080`, then check the deployed HTTPS URL on Android at about 400 px.
The manifest includes local 192 px and 512 px icons and standalone display; Chrome's
**Add to Home screen / Install app** opens it like an app. No offline service worker is
installed. Photo and video inputs use `capture="environment"` to offer the rear camera.
Keep combined uploads below Cloud Run's 32 MiB HTTP/1 request limit; its 900-second
request timeout does not extend an upstream model's timeout.

See [Google's source deployment permissions](https://docs.cloud.google.com/run/docs/configuring/services/build-service-account)
for the account roles used by this deployment.
