# Estimates and review

Estimates runs the whole check as soon as the step opens: it fetches the house's EPC record, reads
every confirmed photo and the bill, and shows two heat-loss estimates side by side (B measured from
the gas bill, A from the building fabric), why they disagree, what was read from each photo, the
named defaults it had to assume and a live verification log. "Ask Gemini to review everything" then
asks one model to explain the gap and propose EPC fields that may be wrong, which code re-tests.

## Sub-features

- `est-running` "Checking your house" with per-source progress ("EPC record working…") and a
  "Verification log (live)" that fills as checks pass or fail.
- `est-hero` "Two estimates": headline ratio card, "Estimate B — measured" and "Estimate A — fabric"
  ranges, comparison chart, "Why they disagree — ranked".
- `est-read` "What we read": one row per photo kind and per radiator ("Radiator k · <label>"),
  VERIFIED / ENTERED BY YOU / NOT PROVIDED / OPTIONAL / couldn't tell, with the fields read; values
  the homeowner entered carry "(you)", and "Your entry and the photo disagree." lists both values
  where they differ.
- `est-defaults` "Named defaults" lists every assumed value.
- `est-no-fabric` missing area or explicit flat/maisonette/park-home: Estimate A explains the gap and fix, B still powers Costs, Spec and Plan; no cross-check or disagreement reasons. Only absence of both estimates refuses sizing, with house-type, area and winter gas usage fixes.
- `est-no-bill` without a gas bill: fabric estimate only, and a statement of what cannot be
  compared.
- `est-review` `Ask Gemini to review everything` -> "Why the estimates differ", "What if the EPC is
  wrong here?" proposals with `Confirm` / `Dismiss`, "Questions to ask", "Removed statements (n)",
  "Review log".
- `est-rerun` `Re-run with current details` runs the check again after photos change.
- `est-error` a failed run shows the error, the log so far and `Try again`.

## How to get to it (user POV)

- `Next: Estimates` on Photos (even with no photos at all).
- Step bar `Estimates` once Photos has been visited; `Back` from Costs or Spec.

## Driving it with drive.sh

Preconditions:

- Photos reached as in [photos](./photos.md), with the photos the case needs.
- Real mode: a house picked with `realhouse`; every run reads each photo with Gemini and costs
  calls.

- **Run with photos.** Add Gas bill, Boiler data plate and two radiators, then
  `click link "Next: Estimates"`. Immediately `shot` shows "Checking your house" with the live log.
  `waitfor "What we read" 90` (only the finished result has it), then `shot` + `snap`: heading "Two
  estimates" (mock adds "OFFLINE DEMO DATA").
- **Every radiator reaches the analysis.** In "What we read" there is one `Radiator k` row per
  radiator card with a photo or entered details, however many photos it had
  (`fjs 'return (d.body.innerText.match(/Radiator \d+/g)||[]).join(",")'`). A details-only card
  reads ENTERED BY YOU. Mock rows are canned per card: prove the payload in real mode (the
  `POST /api/analysis` form, not the screen).
- **Straight to Estimates without photos.** Fresh frame, `click link "Continue"`,
  `click link "Next: Estimates"`. Expected: a result (not an error), Estimate B absent or marked as
  needing a bill, every photo kind NOT PROVIDED, and "Next" offered. Real mode is the meaningful
  check.
- **Review.** `click button "Ask Gemini to review everything"`, `shot` the thinking state,
  `waitfor "Why the estimates differ" 180` (real review takes 1-2 minutes), `into '.review-panel'`,
  `shot`.
- **Back and forward.** `click link "Back"` then `click link "Next: Estimates"`: the same result and
  review come back without a new run.
- **Photos changed after a run.** Go Back, add a photo, return: the old result stays until
  `click button "Re-run with current details"`; after the re-run the new photo is listed.
- **Proof.** `shot` + `snap` of running and finished states, `net` (real: one streaming
  `POST /api/analysis`, and `POST /api/analysis/review` for the review), `apilog` for the Gemini
  lines.

## Gotchas

- Mock analysis reflects only the photo kinds you uploaded; with no photos expect fabric-only
  readings, gaps, and no measured Estimate B. Offline sample labels appear on photo checks and the
  estimates badge in mock mode.
- Quote ticks on the comparison chart come from checked quotes in session only (empty until you check
  quotes).
- After capture changes, a stale banner at the top offers `Re-run with current details` (also at the
  bottom). Known-details and radiator label edits count as input changes too.
- Unknown house geometry uses a low-confidence semi-detached assumption. Explicit non-house geometry has no A; provide a bill including a winter month. Supply missing area on Start.
- The streamed log arrives over one long response: wait for "What we read", not a fixed time. The
  forward button reads `Next: Costs`, or `Next: Spec` when there is no bill (Costs is skipped).
