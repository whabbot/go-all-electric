# Photos: capture, Redact and radiators

Photos lists six evidence slots (Gas bill, Loft, Boiler data plate, Radiators, Fuse cutout, Outdoor
unit spot). Picking or taking a photo opens the Redact dialog, where the user can crop and draw
black boxes over anything identifying before "Use photo" sends only that redacted image for a check.
Radiators accept several photos at once (up to 8), each redacted in turn, listed, and retaken or
removed individually; a radiator walkthrough video is an alternative.

## Sub-features

- `photos-slots` six expandable slots, each with a priority tag (MOST IMPORTANT, RECOMMENDED,
  OPTIONAL), photo count, time hint, `Why do we need this?` and `See examples`.
- `photos-pick` a pick opens the Redact dialog ("Redact your gas bill", "Redact before upload").
- `photos-cancel-repick` Cancel closes the dialog and clears the input, so picking the same file
  again reopens it.
- `photos-redact` crop (`Crop area`, `Crop`, `Undo crop`) and black boxes (`Black out`, `Undo box`);
  the preview is "exactly what will be sent".
- `photos-use` `Use photo` closes the dialog, marks the slot as checking, then shows the verdict.
- `photos-multi` Radiators takes several files from one pick: the dialog shows "Photo i of n";
  `Cancel` skips just that photo; every confirmed photo appears as "Radiator k" with
  `Retake Radiator k` and `Remove Radiator k`.
- `photos-limit` more than 8 radiator photos queues only the first that fit and says so.
- `photos-retake-remove` retake replaces one radiator in place; remove drops it.
- `photos-video` "Or film your radiators": one video (max 100 MB, 90 s) with a privacy warning.
- `photos-examples` `See examples` opens "Example photos: <slot>" with Good/Avoid illustrations.
- `photos-no-bill` without a gas bill the page says you will get the fabric estimate only.

## How to get to it (user POV)

- `Continue` on Start, or the step bar link `Photos`, or `Back` from Estimates.
- Inside the step: the slot's disclosure button (`Gas bill MOST IMPORTANT`, `Radiators RECOMMENDED`,
  ...), then its `📷 Take photo or upload` file input. On a phone this offers the camera or the
  gallery.

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
- **Several radiators at once.** `upload "Radiators" 3`. `coverup` prints
  `Redact before upload | Photo 1 of 3`. `click button "Use photo"` -> `Photo 2 of 3`;
  `click button "Cancel"` -> `Photo 3 of 3`; `click button "Use photo"` -> `closed`. The list
  (`fjs 'return [...d.querySelectorAll(".radiator-list > li")].length'`) holds 2, named after the
  files picked.
- **Retake one.**
  `u=$(uid button "Retake Radiator 2"); chrome-devtools-axi upload @$u "$(synth retake)"`. The
  dialog opens for one photo; after `Use photo` "Radiator 2" shows the new file name and the count
  is unchanged.
- **Remove one.** `click button "Remove Radiator 2"`. The count drops by one.
- **Over the limit.** With 2 radiators, `upload "Radiators" 7`. An alert says "Only the first 6
  photos queued (maximum 8 radiator photos)." and the dialog shows `Photo 1 of 6`.
- **Examples.** `click button "Boiler data plate"`, `click button "See examples"`. Dialog "Example
  photos: Boiler data plate" with `Close` focused; Escape closes it.
- **Skip optional slots.** Leave Outdoor unit spot (OPTIONAL) and Loft empty and press
  `Next: Estimates`; the flow continues.
- **Back and forward.** From Estimates, `click link "Back"`: every slot still reads `Ready`;
  `click link "Next: Estimates"` returns to the same result without re-running.
- **Proof.** `shot` + `snap` of the dialog with its progress label, of the radiator list, and `net`
  (mock: 0 `/api`; real: one `POST /api/photos/check` per confirmed photo).

## Gotchas

- `chrome-devtools-axi upload @uid a b c` sends only the first file. Use `upload SLOT N` for several
  files in one pick.
- Programmatic `upload` always fires `change`; only `pick` (the real file chooser) can prove the
  "same file after Cancel" path, together with `fileinput` showing `"No file chosen"`.
- Snapshot uids go stale after every change; a stale uid makes `axi upload` silently do nothing.
  Resolve with `uid` right before use.
- Slot panels render their radiator list only while expanded; a collapsed Radiators slot reports 0.
- In a several-photo batch `Cancel` skips one photo; there is no button to drop the whole batch, and
  Escape does not close the Redact dialog.
- Cropping (or undoing a crop) removes black boxes drawn before it; draw boxes after cropping.
- Mock checks are canned: a grey synthetic image comes back "Legible" with Sam's readings. Only real
  mode says anything about the image.
