# Plan and Pack

Plan lays out the move off gas in order: electricity supply first when the fuse is too small, then
the heat pump and grant, then solar and EV charging, each with one headline figure. Pack turns
everything into editable drafts the homeowner copies or downloads themselves: one email per checked
quote (optionally drafted by Gemini and number-checked), a house summary for installers and a note
to the network operator. Nothing is ever sent from the app.

## Sub-features

- `plan-steps` "Your all-electric plan" with sections "Electricity supply", "Heat pump + grant",
  "Solar", "EV charging".
- `pack-drafts` "Questions for Quote A" (one per checked quote), "House summary for installers",
  "Draft note to network operator", each an editable textbox "Edit before you share".
- `pack-review-gate` `Copy` and `Download .txt` stay disabled until `I've reviewed this draft` is
  ticked; Copy then says "Copied to clipboard."
- `pack-gemini` `Draft the email with Gemini` (or `Draft all 3 emails with Gemini`) -> "n of n
  drafted by gemini-4-argon", a "Drafting log" with removed sentences; falls back to the template.
- `pack-end` the forward area shows "End of flow"; `Back to plan` and `Back`.

## How to get to it (user POV)

- `Next: Plan` on Quotes (unchecked quotes: `Continue without checking`), then `Next: Pack`.
- Step bar `Plan` / `Pack` once Estimates produced a plan and Spec was visited.

## Driving it with drive.sh

Preconditions:

- A full run through Spec (and Quotes if the emails matter), as in the earlier files.

- **Plan.** `click link "Next: Plan"`. Heading "Your all-electric plan" and the four sections;
  `shot NAME full`, `snap`.
- **Pack.** `click link "Next: Pack"`. Heading "Your pack"; the drafts contain "[your address]",
  never an address, name or meter number.
- **Review gate.** `click checkbox "I've reviewed this draft"`, then `click button "Copy"`: "Copied
  to clipboard." appears under the buttons.
- **Gemini drafts.** `click button "Draft"`, `shot` the in-progress state,
  `waitfor "drafted by" 60`, `shot`. The log shows each number check.
- **Jump ahead after the sample.** Fresh frame, `click button "Load Sam's sample (demo)"`, run
  Estimates, then use the step bar straight to `Quotes`, `Plan`, `Pack`: note which forward buttons
  appear (see Gotchas).
- **Proof.** `shot` + `snap` of Plan and Pack; `net` (real: `POST /api/pack/installer-drafts` with
  numbers and quote labels only).

## Gotchas

- Plan needs an analysis with a plan; without Estimates the step stays locked.
- Steps count as done only once visited. After the sample unlocks everything, jumping ahead still
  shows **Next: Plan** from Quotes and **Next: Pack** from Plan (unchecked quotes use
  **Continue without checking** instead of Skip).
- `Download .txt` triggers a browser download; headless Chrome saves it silently, so assert the
  enabled state rather than the file.
- Never paste or send a draft anywhere; drafts are for the homeowner to send.
