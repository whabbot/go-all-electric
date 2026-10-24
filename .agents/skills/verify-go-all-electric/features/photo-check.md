# Instant photo check

After a photo is redacted and confirmed, the app checks it at once: what it shows, whether it is
legible, key fields already visible, a retake hint, and a warning if a face or number plate may
still be visible. The slot shows a spinner while checking, then the verdict; a failed check shows an
error in the slot instead of hanging.

## Sub-features

- `check-progress` `Checking photo…` status in the slot while the check runs; Next is still allowed,
  with "Wait for photo checks to finish before continuing."
- `check-ok` legible result: verdict line with model and seconds, ✓ Done, "Redacted image only — no
  metadata stored."
- `check-retake` not legible or wrong subject: "Needs attention" and a retake hint.
- `check-privacy` identifying detail warning asking to cover it and resend.
- `check-error` the API fails or times out: an alert in the slot, the photo stays usable.
- `check-per-radiator` each radiator photo is checked separately and shows its own verdict.

## How to get to it (user POV)

- Photos step: `Use photo` in the Redact dialog for any slot.
- Retaking a radiator re-runs its check.

## Driving it with drive.sh

Preconditions:

- Photos step reached as in [photos](./photos.md).
- Real mode for anything about Gemini. In mock the result is canned after 0.6-1.4 s; a file name
  containing `blur` gets the canned retake result.

- **Mock wiring.** `upload "Boiler data plate"`, `click button "Use photo"`, `waitfor "Ready" 10`.
  The slot briefly shows `Checking photo…`, then "Legible — Worcester Greenstar 24 kW combi" with ✓
  Done, and `net` reports `0 /api requests`.
- **Mock retake path.** `upload "Fuse cutout" 1 blurry` (a file name containing `blur`),
  `click button "Use photo"`. The slot reads "Needs attention" and "Couldn't read this — too
  blurry".
- **Real backend path (one Gemini call).** `photocheck boiler_plate`. Expect `HTTP 200` within about
  10 s and a JSON body whose `legible` is `false` with a `retake_hint` (the image is a grey
  synthetic card, not a plate). Then `apilog photocheck`: the log has one line with
  `"purpose": "/api/photos/check:boiler_plate"`, the model, `latency_ms` and `"outcome": "ok"`.
- **Real UI path.** After `realhouse`, `click link "Continue"`, `upload "Boiler data plate"`,
  `click button "Use photo"`, `waitfor "Needs attention" 60`. `net` shows one
  `POST /api/photos/check` with 200.
- **Hang guard.** Any check still `Checking photo…` after 60 s is a failure; capture `shot`, `net`
  and `apilog` and report the timing.
- **Proof.** Real-mode proof is the `photocheck` JSON, the `apilog` line and (UI path) a `shot` of
  the slot verdict plus `net`.

## Gotchas

- `/api/photos/check` is rate-limited per IP (30 Gemini calls an hour locally by default); a 429
  shows its message in the slot. Do not loop real checks.
- Mock backend has no key: `photocheck` there returns 503, which proves nothing about Gemini.
- Never send a real photo to "make it pass". A grey synthetic card being reported as not legible is
  the correct, honest result.
- Gemini never receives an address or postcode; the check request carries only `kind` and the
  redacted image.
