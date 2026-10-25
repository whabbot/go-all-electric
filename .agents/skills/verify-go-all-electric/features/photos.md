# Photos: capture, Redact and radiators

Photos lists six evidence slots (Gas bill, Loft, Boiler data plate, Radiators, Fuse cutout, Outdoor
unit spot). Picking or taking a photo opens the Redact dialog, where the user can crop and draw
black boxes over anything identifying before "Use photo" sends only that redacted image for a check.
Radiators are added one card at a time (`+ Add radiator`, up to 8): each card has a room label (pick
list plus a short note, shown only to the homeowner), up to 3 photos of that one radiator (read
together as one radiator) and an "Add details you know" expander. Boiler data plate and Fuse cutout
have the same expander. A radiator walkthrough video is an alternative.

## Sub-features

- `photos-slots` six expandable slots, each with a priority tag (MOST IMPORTANT, RECOMMENDED,
  OPTIONAL), photo count, time hint, `Why do we need this?` and `See examples`.
- `photos-pick` a pick opens the Redact dialog ("Redact your gas bill", "Redact before upload").
- `photos-cancel-repick` Cancel closes the dialog and clears the input, so picking the same file
  again reopens it.
- `photos-redact` crop (`Crop area`, `Crop`, `Undo crop`) and black boxes (`Black out`, `Undo box`);
  the preview is "exactly what will be sent".
- `photos-use` `Use photo` closes the dialog, marks the slot as checking, then shows the verdict.
- `photos-cards` `+ Add radiator` adds a "Radiator k" card (focused, scrolled into view) with
  `Room`, `Note (optional)`, `Add photos of Radiator k` and `Remove Radiator k`; at 8 cards the
  button is disabled.
- `photos-multi` one card takes several files from one pick: the dialog shows "Photo i of n";
  `Skip this photo` skips just that one, `Cancel all` drops the rest of the batch, Escape acts like
  Skip/Cancel; every confirmed photo appears as "Photo j" on that card, which reads
  "j of 3 photos: all read together as this one radiator".
- `photos-limit` more than 3 photos on one card queues only the first that fit and says so; the
  notice clears when the queue finishes.
- `photos-retake-remove` `Retake Radiator k photo j` replaces one photo in place;
  `Remove Radiator k photo j` drops it.
- `photos-details` "Add details you know" (closed by default) on each radiator card (type with a
  plain-language picker, panels, fin rows, width and height in mm), on Boiler data plate (make,
  model, heating and hot-water kW) and on Fuse cutout (rating). Out-of-range values show an inline
  message. A card or slot with details and no photo counts as done.
- `photos-video` "Or film your radiators": one video (max 100 MB, 90 s) with a privacy warning.
- `photos-examples` `See examples` opens "Example photos: <slot>" with Good/Avoid illustrations.
- `photos-no-bill` without a gas bill the page says you will get the fabric estimate only.

## How to get to it (user POV)

- `Continue` on Start, or the step bar link `Photos`, or `Back` from Estimates.
- Inside the step: the slot's disclosure button (`Gas bill MOST IMPORTANT`, `Radiators RECOMMENDED`,
  ...), then its `📷 Take photo or upload` file input (`Replace photo` once the slot has one). On a
  phone this offers the camera or the gallery. Radiators: `+ Add radiator`, then the card's
  `Take photo or upload` input.

## Driving it with drive.sh

Preconditions:

- Fresh `frame 390 844 /`, then `click button "Load Sam's sample (demo)"` and
  `click link "Continue"` (mock), or `realhouse` and `click link "Continue"` (real).
- Synthetic images only: `upload` draws them in the page, `synth NAME` writes one to disk.

- **Single photo.** `pick "Gas bill" "$(synth gas-bill)"`. `coverup` prints
  `Redact your gas bill | single photo`. `fileinput "Gas bill"` prints `"No file chosen"` (input
  already cleared).
- **Cancel then the same file again.** `click button "Cancel"`; `coverup` prints `closed`.
  `pick "Gas bill" "$GAE_STATE/fixtures/gas-bill.png"` again; the dialog reopens.
- **Redact.** `blackout` draws a box; `shot` shows it on the preview. `crop` crops to the centre;
  the preview shrinks. `Undo box` / `Undo crop` enable after each.
- **Use photo.** `click button "Use photo"`. The slot shows `Checking photo…` (role status), then
  its row reads `· Ready` with a ✓ Done badge and the verdict (see [photo-check](./photo-check.md)).
- **Add a radiator.** `click button "Radiators"`, `click button "+ Add radiator"`. A "Radiator 1"
  card appears with `Room` focused. Pick a room: `u=$(uid combobox "Room"); $AX fill @$u "Hall"`;
  the card title reads "Radiator 1 · Hall".
- **Several photos of one radiator.** `upload "Radiator 1" 3`. `coverup` prints
  `Redact before upload | Photo 1 of 3`. `click button "Use photo"` -> `Photo 2 of 3`;
  `click button "Skip this photo"` -> `Photo 3 of 3`; `click button "Use photo"` -> `closed`. The
  card reads "2 of 3 photos: all read together as this one radiator".
- **Cancel the whole batch.** `upload "Radiator 1" 3`, then `click button "Cancel all"`: `coverup`
  prints `closed` and no photo was added. Escape in the dialog acts like `Skip this photo` (or
  `Cancel` for a single photo).
- **Details only.** On a new card, open "Add details you know"
  (`fjs 'd.querySelectorAll(".radiator-card")[1].querySelector("summary").click()'`), pick a Type by
  its label (`Double panel, two sets of fins`), then `fill Width 900 "Radiator 2"` and
  `fill Height 600 "Radiator 2"`. Only card 2 changes; card 1’s closed fields stay empty.
  The summary shows "N added";
  the Radiators row reads `· Ready` even with no photo.
- **Retake one.**
  `u=$(uid textbox "Retake Radiator 1 photo 2"); chrome-devtools-axi upload @$u "$(synth retake)"`
  (or find the input by that aria-label). The dialog opens for one photo; after `Use photo` the card
  shows the new file name and the count is unchanged.
- **Remove one.** `click button "Remove Radiator 1 photo 2"`. The count drops by one;
  `click button "Remove Radiator 1"` drops the whole card.
- **Over the limit.** With 1 photo on a card, `upload "Radiator 1" 4`. An alert says "Only the
  first 2 photos queued (up to 3 per radiator)." and the dialog shows `Photo 1 of 2`; the alert is
  gone once the queue is done.
- **Examples.** `click button "Boiler data plate"`, `click button "See examples"`. Dialog "Example
  photos: Boiler data plate" with `Close` focused; Escape closes it.
- **Skip optional slots.** Leave Outdoor unit spot (OPTIONAL) and Loft empty and press
  `Next: Estimates`; the flow continues.
- **Back and forward.** From Estimates, `click link "Back"`: every slot still reads `Ready`;
  `click link "Next: Estimates"` returns to the same result without re-running.
- **Proof.** `shot` + `snap` of the dialog with its progress label, of the radiator cards, and `net`
  (mock: 0 `/api`; real: one `POST /api/photos/check` per confirmed photo). Labels never leave the
  browser: in real mode the `POST /api/analysis` form has `radiators` + `radiator_index` per photo
  and one `known` JSON field, with no room or note.

## Gotchas

- `chrome-devtools-axi upload @uid a b c` sends only the first file. Use `upload SLOT N` for several
  files in one pick.
- Programmatic `upload` always fires `change`; only `pick` (the real file chooser) can prove the
  "same file after Cancel" path, together with `fileinput` showing `"No file chosen"`.
- Snapshot uids go stale after every change; a stale uid makes `axi upload` silently do nothing.
  Resolve with `uid` right before use.
- Slot panels render their radiator cards only while expanded; a collapsed Radiators slot reports 0.
  Cards live in memory only: a Vite hot reload or page reload drops them.
- `upload "Radiators" N` no longer works (the row has a `+ Add radiator` button, not a file
  input): add a card, then `upload "Radiator k" N`.
- Open the target card’s "Add details you know" before filling. `fill Width 900` uses the only
  visible Width input; `fill Width 900 "Radiator 2"` restricts it to that card. Closed details
  are excluded. Multiple visible matches fail instead of silently choosing another card.
- Selects take the option's visible label with `$AX fill`, not its value (`Double panel, two sets
  of fins`, not `K2`).
- Cropping then drawing boxes, or boxes then crop, both survive **Undo crop** and export; boxes
  drawn before crop are merged back onto the full image when you undo.
- Mock checks are canned: a grey synthetic image comes back "Legible" with Sam's readings. Only real
  mode says anything about the image.
