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
- `quotes-forward` optional step: `Continue without checking` when uploads are unchecked, else
  `Next: Plan` (no separate Skip).

## How to get to it (user POV)

- `Next: Quotes` on Spec; step bar `Quotes (opt)`; `Back` from Plan.

## Driving it with drive.sh

Preconditions:

- Spec visited (see [costs-spec](./costs-spec.md)).
- Synthetic quote pages only. Sample PDFs live in `demo/quotes/` (`sample-quote-a.pdf` ...); they
  are labelled SAMPLE and safe to upload.

- **Sample quotes (mock).** `click button "Load Sam's three quotes"`,
  `waitfor "Questions to ask before signing" 20`. Three cards "Quote A", "Quote B", "Quote C"; A and
  B flagged oversized; C is inside the target range.
- **Own quote page.**
  `u=$(uid button "📷 Choose PDFs"); chrome-devtools-axi upload @$u "$(synth quote-1)"`. `coverup`
  prints `Redact quote page — quote-1.png | single photo`; `click button "Use photo"`; the list
  shows "Quote A"; `click button "Check quotes"`; a card appears.
- **PDF quote.** Upload `demo/quotes/sample-quote-a.pdf` the same way: the dialog title walks "...
  sample-quote-a.pdf page 1", "page 2"; after the last page the list shows one quote, and
  `Check quotes` gives one card for the whole PDF.
- **Unchecked forward.** `click link "Continue without checking"` goes to Plan without checking.
- **Proof.** `shot` + `snap` of the cards; `net` (real: one `POST /api/quotes/check` carrying page
  images only, never the PDF).

## Gotchas

- Mock checks are canned: any uploaded page comes back as a 9 kW, 55 °C quote with a buffer tank.
- Each quote has a stable id: replacing one never inherits another quote's check result; Remove
  drops only that quote's card. Unchecked uploads stay after `Continue without checking` and Back.
- Footer shows `Continue without checking` (not a duplicate Skip) when uploads are unchecked; `Check
  quotes` stays the primary action on the page. Max three quotes; use Remove to free a slot.
- Real quote checks call Gemini per quote; keep to one synthetic page or one sample PDF.
