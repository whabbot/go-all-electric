---
name: verify-go-all-electric
description: Launch Go All-Electric (FastAPI backend + Vite React frontend) in an isolated local instance, drive the guided flow in a browser the way a homeowner does (phone width included) with chrome-devtools-axi, and capture screenshot/ARIA/network evidence. Use after any change to the frontend, the API or the Gemini/EPC paths, before opening or approving a PR, and whenever a bug report needs reproducing in the running app. Mock mode needs no keys; real mode calls Gemini and EPC.
---

# Verify Go All-Electric in the running app

Unit tests do not catch what a user hits: a dialog that will not reopen, a picker that keeps one
file of three, a check that hangs, a screen that shows numbers for photos nobody took. This skill
starts your own copy of the app, drives it through the real user path, and leaves evidence a
reviewer can check. Read [`features/README.md`](features/README.md) next, then the feature file for
what you changed.

All paths below are relative to the worktree root. Never start a command with `cd`; the scripts find
the worktree themselves.

## Launch

```bash
.agents/skills/verify-go-all-electric/scripts/launch.sh mock    # default: no keys, Sam's sample data
.agents/skills/verify-go-all-electric/scripts/launch.sh real    # live /api, real Gemini + EPC
```

- **mock**: the frontend runs with `VITE_USE_MOCKS=true` and answers every call from Sam's built-in
  sample (no `/api` traffic at all). The backend still starts, with every key unset, so
  `/api/health` and keyless endpoints work. Free, offline, deterministic.
- **real**: the frontend runs with `VITE_USE_MOCKS=false` and calls the backend through Vite's
  `/api` proxy. Only `GEMINI_API_KEY` and `EPC_API_TOKEN` are read from
  `~/.config/go-all-electric/.env` (override with `GAE_ENV_FILE`) into the backend process
  environment; nothing is printed or copied. MongoDB, `ACCESS_CODE_HASH`/`SESSION_SECRET` and the
  retired `ACCESS_CODE` are deliberately not loaded: surveys are not saved and there is no sign-in
  screen. Every photo check, analysis, review and draft costs real Gemini calls: drive only what you
  need.

The launcher picks two free ports (or `GAE_BACKEND_PORT`/`GAE_FRONTEND_PORT`), runs the backend from
`.verify/run` so no stray `.env` can leak in, installs missing deps (`uv sync --frozen`, `npm ci`),
and returns only when the instance is usable: backend health answers, Vite has compiled
`src/main.tsx` in the requested mode, and the `/api` proxy reaches this run's backend. It prints the
app URL, the phone-harness URL and the evidence directory. One instance per worktree: a second
`launch.sh` refuses while the first is alive.

Everything about the run is in `.verify/run/env`; `drive.sh` sources it for you. For other tools:
`. .verify/run/env` gives `GAE_URL` (app), `GAE_API` (backend), `GAE_MODE`, `GAE_EVIDENCE` and this
worktree's own `CHROME_DEVTOOLS_AXI_SESSION`, so your browser never collides with another worker's.

## Doctor

```bash
.agents/skills/verify-go-all-electric/scripts/doctor.sh
```

Read-only. Run it first, and again whenever anything looks off. It checks both PIDs are alive and
own their ports, `/api/health` shows the integrations the mode expects (mock: none; real: Gemini and
EPC, never MongoDB), the frontend is compiled with the matching `VITE_USE_MOCKS`, the proxy reaches
this backend, `/__frame.html` is served, and the backend code has not changed since launch. Vite
hot-reloads frontend edits; **the backend does not reload**: after editing `backend/src`,
`teardown.sh` and `launch.sh` again.

## Drive

```bash
. .agents/skills/verify-go-all-electric/scripts/drive.sh      # bash or zsh
evidence photos-multi-radiator                                 # sets $EV for this proof
frame 390 844 /                                                # phone width, fresh session
click button "Load Sam's sample (demo)"; click link "Continue"
click button "Radiators"; click button "+ Add radiator"
upload "Radiator 1" 3; coverup                                  # -> Redact before upload | Photo 1 of 3
click button "Use photo"; click button "Skip this photo"; click button "Use photo"
shot 01-radiators; snap 01-radiators; net 01
```

`drive.sh` wraps `chrome-devtools-axi` and enables `set -e`: source it in a dedicated verification
shell. A missing control, ambiguous fill or `waitfor` timeout returns non-zero and stops the
remaining commands in a sequence, including commands separated by `;`. Do not wrap a whole
sequence in `if`, `!` or `||`: shells suppress errexit there. Resolve failures before continuing.
`uid`, `click`, file-input lookup and saved snapshots use `snapshot --full`; `waitfor` reads the
app document's visible text directly, without snapshot truncation.

Helpers (all print one short line):

| Helper | Does |
| --- | --- |
| `frame W H PATH [keep]` | Loads the app at `PATH` inside a `W`x`H` iframe (`/__frame.html`, served from `frontend/public/`). Clears `sessionStorage` unless `keep`. **The only way to test phone width**: `chrome-devtools-axi resize` cannot go below about 500 px. |
| `desk PATH` | Loads the app as a plain 1280x800 page. |
| `click ROLE NAME` | Real click on the element whose role and accessible name start with `NAME`, resolved from a fresh snapshot (works inside the iframe). Prefer this. |
| `tap TEXT` | JS click on the first visible button/link/label with that text. Fallback for ambiguous names. |
| `fill LABEL VALUE [SCOPE]` | Sets one visible, editable labelled input (`fill Postcode "N10 2AB"`). Optional card/region heading: `fill Width 900 "Radiator 2"` (also matches "Radiator 2 · Hall"). Open its details first. Hidden fields are excluded; multiple visible matches fail, so use a scope. Sample or synthetic values only. |
| `upload SLOT [N] [PREFIX]` | Puts `N` synthetic images into a Photos slot's file input in one pick (several files at once). `SLOT` is the slot label: `Gas bill`, `Loft`, `Boiler data plate`, `Radiator 1` (add its card first), `Fuse cutout`, `Outdoor unit spot`. |
| `synth NAME` / `pick SLOT FILE` | Writes a synthetic PNG to `.verify/run/fixtures/`; `pick` chooses it through the slot's real file chooser (CDP, one file). Use `pick` to re-choose the **same file** after Cancel. |
| `fileinput SLOT` | The slot input's value as the browser shows it: `"No file chosen"` means re-picking the same file will fire `change`. |
| `coverup` | State of the Redact dialog: `closed`, or its title and `Photo i of n`. |
| `blackout` / `crop` / `drag X1 Y1 X2 Y2` | Draw a black box, crop to the centre, or drag between fractional points on the Redact canvas. |
| `has TEXT` / `waitfor TEXT [S]` / `where` | Visible-text check, poll (no fixed sleeps), current path. |
| `go PATH` | Client-side navigation keeping in-memory state (deep link; not what a user does, so not proof of navigation). |
| `fjs BODY` | Run JS against the app document `d` / window `w` (inside the iframe when framed). Read state with it; do not use it to change state a user could not. |
| `shot NAME [full]`, `snap NAME`, `net NAME`, `apilog NAME`, `note TEXT` | Evidence: screenshot (just the app frame; `full` = whole page), ARIA snapshot, the `/api` requests this backend served since the last `net` (from its access log, because the browser list misses the iframe's fetches) plus the browser network list, backend log copy, transcript line. |
| `audit` | Layout, contrast, text-size and tap-target checks of the current state, as JSON. |
| `photocheck KIND [FILE]` | Real mode: posts a synthetic image to `/api/photos/check` through the app's proxy (the exact request the Photos step sends) and prints status, time and reply. |
| `realhouse` | Real mode: picks a house from a postcode kept in a private file (`GAE_VERIFY_POSTCODE_FILE`, default `~/.config/go-all-electric/verify-postcode`) without printing it or the address list. Live mode has no sample house, so the Photos step and later need this. |

Raw `chrome-devtools-axi snapshot` lists the iframe's contents with roles and names, so you can also
`chrome-devtools-axi click @<uid>` directly. Snapshot uids carry a generation prefix (`g12:3_4`) and
go stale after the page changes: resolve a uid right before using it (`click` and `pick` do).

`scripts/walk.sh [NAME]` (mock mode) screenshots every step at 390x844 and 1280x800 with audit JSON.
It is a layout and wiring smoke test of the happy path, not a feature proof.

### Real mode

1. `launch.sh real`, then `doctor.sh` must show Gemini and EPC configured and MongoDB not.
2. Prove the backend path with `photocheck boiler_plate` (one Gemini call, synthetic image). The
   synthetic image is not a boiler plate, so the honest answer is "not legible" plus a retake hint;
   anything else (a confident reading of a grey picture) is a bug. `apilog` captures the structured
   Gemini call line (`purpose`, `model`, `latency_ms`, `outcome`), which proves a real call happened
   and how long it took.
3. To drive the UI past Start you need a house: `realhouse` (requires the private postcode file; if
   it does not exist, ask the operator who holds the keys for one (never commit it) and report the
   UI path as not verified). After that, use the same helpers as mock mode with synthetic images
   only.

## Evidence

Evidence lives in `.verify/evidence/<date>-<name>/` inside the worktree. `.verify/` is gitignored
and `teardown.sh` never deletes `evidence/`. Copy what a reviewer needs into the PR (or the task's
proof directory) before the worktree is recycled.

Proof standards:

- **Real user path.** Start from a fresh `frame`/`desk`, reach the feature through the step bar,
  Back/Next and the on-screen buttons. `go` and `fjs` state changes are setup shortcuts, never the
  proof.
- **Action and resulting state.** Capture before and after each user action (`shot` + `snap`), not
  just the final screen. For async work (photo check, analysis, review, drafts) capture the
  in-progress state too, and use `waitfor` so a hang shows up as a timeout instead of a long sleep.
- **Side effects and network.** `net` lists the `/api` calls this run's backend served since the
  previous `net`, with status. Mock mode must show `0 /api requests`; a real-mode proof must show
  the expected `/api` call with a 2xx status, plus `apilog` for the Gemini call line.
- **Say which mode.** Every report states `mock` or `real`. Only the mock Estimates screen carries
  an "OFFLINE DEMO DATA" tag; mock photo checks (even the ones naming a Gemini model), readings and
  quote results are all canned: they prove UI wiring, never Gemini, EPC or maths behavior. Never
  present a mock result as live.
- **Edge paths are part of the proof.** The feature files list the paths real users take (cancel
  then re-pick the same file, several files at once, skip optional steps, straight to Estimates
  without photos, Back then Next). A change to a step is verified only when its listed paths are.
- **Report what you could not reach** with the command you tried and the missing precondition, never
  a different path presented as the same thing.

Privacy rules for evidence: synthetic images and Sam's sample only. No real photos, bills, addresses
or postcodes in screenshots, snapshots, logs or the repo. In real mode take no screenshot of the
Start screen while a postcode or address list is visible; after `realhouse` the app shows only the
district. Never print or copy the keys file.

## Cleanup

```bash
.agents/skills/verify-go-all-electric/scripts/teardown.sh
```

Stops the two PIDs `launch.sh` recorded (never by process name) and this worktree's
chrome-devtools-axi session, removes `.verify/run`, and keeps `.verify/evidence`. Run it after every
attempt, failed ones included, so no ports or browsers are stranded. It warns, and leaves alone, any
port now held by someone else.

## Helpers

All in `scripts/`, executable:

- `launch.sh [mock|real]`, `doctor.sh`, `teardown.sh`: lifecycle, shown above.
- `drive.sh`: sourced browser helpers (table above).
- `walk.sh [NAME]`: mock smoke walk of every step at two sizes.
- `audit.js`: the checks behind `audit`; also
  `chrome-devtools-axi eval "$(cat .agents/skills/verify-go-all-electric/scripts/audit.js)"`.

The phone harness itself is `frontend/public/__frame.html` (`?w=390&h=844&path=/capture`, add
`&keep` to keep `sessionStorage`). It is plain static HTML; Vite serves it in every mode.

## Keeping the map honest

When you change a screen, update its feature file in the same PR: new or renamed buttons, new edge
paths, and any gotcha you hit while driving it. A label in `features/` or `walk.sh` that no longer
exists shows up as `MISSING button "..."` on the next run.
