# Go All-Electric verification map

This directory is the maintained source for verifying what a homeowner can do in Go All-Electric.
Read this index before driving the app, then use the matching feature file as the recipe. The app is
one guided flow of eight steps (Start, Photos, Estimates, Costs, Spec, Quotes, Plan, Pack); each
file below covers one or two of them.

## Baseline preconditions

- An instance from this worktree, started with `scripts/launch.sh mock` (or `real`), and
  `scripts/doctor.sh` printing `doctor: ok`.
- Helpers sourced: `. .agents/skills/verify-go-all-electric/scripts/drive.sh`, and an evidence
  directory chosen with `evidence <name>`.
- Phone width (390x844) through `frame`; projector/desktop size (1280x800) through `desk`. Photos
  and Redact flows are phone-first: verify them framed.
- Mock mode: Sam's sample is the house (`N10 2AB` -> `14 Oakwood Avenue`, shown as "house in N10").
  Real mode: a house only via `realhouse` and the operator's private postcode file.
- Never drive an instance this worktree did not start, and never the deployed site.

## Driving conventions

- Start each recipe from a fresh `frame` (it clears `sessionStorage`) unless it says otherwise.
- Move between steps the way a user does: the step bar links (`click link "Photos"`), `Back`,
  `Next: <step>`, `Skip`, `Continue`. Use `go PATH` only to set up a precondition.
- Prefer `click ROLE NAME` with the accessible names quoted in each file; they are the contract.
- Photos go in through `upload` (several at once) or `pick` (one real file choice). Always synthetic
  images.
- Wait with `waitfor TEXT`, never fixed sleeps: a hang must show up as a timeout.

## Proof and skip reporting

- Pair each user action with the resulting state: `shot` + `snap` before and after.
- Network: `net` after async steps. Mock must show `0 /api requests`. Real must show the expected
  `/api` call and status, plus `apilog` for the Gemini call line.
- State the mode on every artifact set. Mock results are canned: they prove UI wiring only.
- Record the feature file and entry point you used. If an entry point or edge path is unreachable,
  report the attempted command and the unmet precondition; do not substitute another path.

## Feature entry contract

Each feature file starts with an H1 title and one paragraph describing the user-visible behavior. It
then uses exactly four H2 sections in this order.

1. `Sub-features` lists short IDs with one line for each behavior.
2. `How to get to it (user POV)` lists every user entry point.
3. `Driving it with drive.sh` starts with `Preconditions:` and uses labeled bullets that pair each
   user action with an exact helper command and its observable result. Edge paths are bullets too.
4. `Gotchas` lists traps that can waste or invalidate a verification run.

Keep implementation details out of the map: user paths, accessible names, required state, commands
and observable proof only.

## Features

- [Start and property lookup](./start.md): postcode search, picking a house, Sam's sample, what
  unlocks.
- [Photos: capture, Redact and radiators](./photos.md): slots, file picking, the Redact
  (crop/cover-up) dialog, several radiator photos, retake/remove, walkthrough video.
- [Instant photo check](./photo-check.md): the per-photo check after Redact, its states and timing,
  real Gemini proof.
- [Estimates and review](./estimates.md): running the analysis, the two estimates, what was read,
  the Gemini review, no-photo and partial-photo paths.
- [Costs and Spec](./costs-spec.md): savings by flow temperature, the target spec, optional Costs.
- [Quotes](./quotes.md): uploading and redacting quote pages, Sam's three quotes, flags, Skip.
- [Plan and Pack](./plan-pack.md): the sequenced all-electric plan and the editable drafts.
