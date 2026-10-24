# Quotes

Quotes lets a homeowner upload up to three installer quotes (PDFs or photos). Every page goes
through the same Redact dialog as photos before anything is sent; PDFs are turned into page images
in the browser first. "Check quotes" reads each one and flags it against the target size: likely
oversized, high design flow, buffer tank, grant not deducted, kW not matching the datasheet, with
questions to ask before signing. The step is optional.

## Sub-features

- `quotes-upload` `📷 Choose PDFs or photos (max 3)`; each page opens "Redact quote page — <file>".
- `quotes-list` uploaded quotes are listed as "Quote A", "Quote B", ... (never by file name).
- `quotes-check` `Check quotes` (disabled until a quote is added) -> one card per quote with the
  quoted size, design flow, flags and "Questions to ask before signing".
- `quotes-sample` mock only: `Load Sam's three quotes (demo)` loads and checks Sam's A, B, C.
- `quotes-review` the review panel from Estimates appears here with
  `Review again with N checked quotes`.
- `quotes-skip` optional step: `Skip` and `Next: Plan`.

## How to get to it (user POV)

- `Next: Quotes` on Spec; step bar `Quotes (opt)`; `Back` from Plan.

## Driving it with drive.sh

Preconditions:

- Spec visited (see [costs-spec](./costs-spec.md)).
- Synthetic quote pages only. Sample PDFs live in `demo/quotes/` (`sample-quote-a.pdf` ...); they
  are labelled SAMPLE and safe to upload.

- **Sample quotes (mock).** `click button "Load Sam's three quotes"`,
  `waitfor "Questions to ask before signing" 20`. Three cards "Quote A", "Quote B", "Quote C"; B and
  C flagged oversized.
- **Own quote page.**
  `u=$(uid button "📷 Choose PDFs"); chrome-devtools-axi upload @$u "$(synth quote-1)"`. `coverup`
  prints `Redact quote page — quote-1.png | single photo`; `click button "Use photo"`; the list
  shows "Quote A"; `click button "Check quotes"`; a card appears.
- **PDF quote.** Upload `demo/quotes/sample-quote-a.pdf` the same way: the dialog title walks "...
  sample-quote-a.pdf page 1", "page 2"; after the last page the list shows one quote, and
  `Check quotes` gives one card for the whole PDF.
- **Skip.** `click link "Skip"` goes to Plan without checking anything.
- **Proof.** `shot` + `snap` of the cards; `net` (real: one `POST /api/quotes/check` carrying page
  images only, never the PDF).

## Gotchas

- Mock checks are canned: any uploaded page comes back as a 9 kW, 55 °C quote with a buffer tank.
- Adding your own quote after Sam's three replaces the checked list with just yours; the review
  panel below may still mention the earlier quotes until you review again.
- `Skip` and `Next: Plan` lead to the same place; neither checks unchecked uploads.
- Real quote checks call Gemini per quote; keep to one synthetic page or one sample PDF.
