# Demo inputs

Sam, the three installers, their prices, heat losses and quotations are **sample material**.
Every page says **SAMPLE - not a real quote**. Manufacturer names and models come from the
public datasheet seed; no installer name, logo, real address or postcode is used. These are
synthetic documents made in code, never real installer quotes or evidence of a site survey.

| File | Output | Flow | Grant | Intended checker result |
| --- | --- | --- | --- | --- |
| `quotes/sample-quote-a.pdf` | 6 kW | 45 C | GBP 7,500 deducted | Inside range; no red flags |
| `quotes/sample-quote-b.pdf` | 9 kW | 50 C | GBP 7,500 deducted | Oversized |
| `quotes/sample-quote-c.pdf` | 12 kW | 55 C | Not deducted | Oversized; high flow; buffer; grant |

All three have two pages: equipment/design followed by itemised price and grant treatment.
Their default final prices are GBP 4,500, GBP 5,400 and GBP 14,450 respectively. C also states
an inflated 8.8 kW design heat loss. Upload each PDF as one quote through the app; both pages
must stay together so the reader can check the grant and sum the line items.

The existing checker uses **red** for oversizing and the undeducted grant, **amber** for
55 C flow, buffer tank and inflated heat loss. It does not flag exactly 50 C. Those are the
current rules, not claims that every issue appears red. No checker code is changed here.

## Regenerate from the house's numbers

From the repository root, substitute the maths core's target range and central measured load:

```bash
uv run --project demo python demo/generate_quotes.py --size-low-kw 5 --size-high-kw 7 --design-load-kw 4.7 --output private/sample-quotes
```

This one command installs the isolated demo dependencies and generates all three PDFs.
Use `--output demo/quotes` (or omit it) to reproduce the committed Sam defaults. Keep
house-derived variants in `private/`; their heat-loss numbers are still personal data.
The generator never accepts an address or reads photos, bills, secrets or the network.

A uses the seeded model nearest the range midpoint, inside the range. B and C choose distinct
seeded capacities nearest 1.5x and 2x the upper bound (ties prefer smaller), both above the
range. The small seed limits the choice: for 5-7 kW this gives 6/9/12 kW, rather than exact
multiples of 7. Unsupported ranges fail clearly instead of inventing a model or a match.
C's stated loss is deliberately inflated above both the measured load and range top.

## Capture checklist (real gas-heated house)

No real house photos or bills are included yet. Capture these only with the owner's consent:

- **Boiler data plate:** make, model and heating output in kW; hot-water kW and GC number if
  visible. Make the small print sharp. Avoid confusing hot-water capacity with heating output.
- **Radiators in the main rooms:** whole radiator, panel/fin type visible from above, tape
  measure showing width and height; note the room name. Use a close crop without room clues.
- **Main fuse cutout label:** rating in A, not the meter or consumer unit. Photograph only
  what is safely visible; do not remove covers or disturb seals.
- **A year of gas usage:** annual statement or supplier app's 12-month page, kWh and exact
  date range, monthly figures if shown. Cover name, address, account number and MPRN.
- **No outdoor-space photo.** It is skipped in this demo; do not invent a real site assessment.

If a plate is blurry, retake it closer and square-on with better lighting. If the bill is
missing, obtain the supplier's annual kWh view; never present sample gas usage as real.
Keep the app's “couldn't tell”, confidence and retake guidance visible where applicable.

## Privacy on the demo screen

Real photos, bills and derived house-specific documents live **only in gitignored `private/`**.
Never add them to Git, PR attachments or public screenshots. The committed PDFs are samples.
Do not commit API keys; use server-side environment configuration. Nothing goes to installers
or network operators: it advises; you decide.

Pick the address **off-camera**. On the presentation screen show **the postcode area only**
(for example `SW`), never a full address or full postcode. This is an operator checklist;
check the screen before recording or sharing it.

Every real image must pass through the app's on-device **cover-up step** before upload:
crop to the label/radiator/usage, cover names, addresses, account numbers, MPRN, serial numbers,
faces, reflections, house numbers, street signs and anything that could identify the home.
Inspect every page's “exactly what will be sent” preview before confirming. The app re-encodes
images to strip metadata; this does not hide identifying details visible in the picture.
Do not upload originals directly to Gemini or use this sample-only live-check script for real
material. Choose the useful readings without identifying the home.

## Validation

```bash
uv run --project demo pytest demo/tests
```

Tests independently extract the PDF line-item amounts and final total, check that they add up,
verify two pages and the SAMPLE mark on every page, confirm seeded outputs and the intended
design choices, regenerate supported house ranges, reject unsupported inputs and check that
the committed defaults are reproducible.

Optional live verification (paid Gemini calls; only the six synthetic pages leave the machine):

```bash
uv run --project backend --with pymupdf python demo/check_live.py
```

This reads credentials directly from `~/.config/go-all-electric/.env`, without copying or
printing them. It renders PDFs into separate page images in memory and POSTs them to the real
`/api/quotes/check` handler through FastAPI's in-process HTTP test client with parallel
`quote_index` / `quote_name` arrays and the default 5-7 kW / 4.7 kW context. The actual Gemini
read/check/re-read loop runs; datasheet matching uses the public seed, without Atlas. Only
safe status/flag summaries are printed. Missing Gemini configuration skips the live check.
If the configured model cannot run, report that limitation rather than changing extractors.
