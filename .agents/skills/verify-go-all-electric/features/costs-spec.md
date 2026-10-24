# Costs and Spec

Costs compares a year of heating with gas against a heat pump at four flow temperatures (40, 45, 50
and 55 °C) at the current price cap, as ranges, and names the flow temperature above which the heat
pump costs more. Spec turns the estimates into what a good installation must look like: heat pump
size range, maximum flow temperature, radiator upsizing and the grant.

## Sub-features

- `cost-breakeven` the callout "Above about N °C flow, the heat pump costs more than gas."
- `cost-chart` "Annual saving vs gas (£/yr)" bar chart with error bars by flow temperature.
- `cost-cards` one card per flow temperature: gas cost ("KNOWN FROM BILLS"), heat pump cost and
  saving, each low–central–high.
- `cost-optional` with no bill there are no costs: Costs is marked optional, Estimates' forward
  button goes straight to `Next: Spec`, and Costs offers `Skip`.
- `spec-size` "Heat pump size" target range.
- `spec-flow` "Maximum flow temperature" with confidence.
- `spec-radiators` "Radiators": per-radiator output at the target flow and which need upsizing.
- `spec-grant` "Grant": the Boiler Upgrade Scheme amount.

## How to get to it (user POV)

- `Next: Costs` on Estimates, then `Next: Spec`.
- Step bar `Costs` / `Spec` once Estimates has a result; `Back` from Quotes.

## Driving it with drive.sh

Preconditions:

- Estimates finished as in [estimates](./estimates.md), with a gas bill for the Costs path.

- **Costs.** `click link "Next: Costs"`. Heading "Costs", "house in N10", the break-even callout and
  four cards headed "40 °C flow" to "55 °C flow". `shot NAME full` captures the chart and cards.
- **Spec.** `click link "Next: Spec"`. Heading "Target spec" with the four sections above; `snap`.
- **No-bill path (real mode only; mock always has Sam's bill).** Run Estimates without a gas bill.
  The forward button reads `Next: Spec`; the step bar shows `Costs (opt)`; opening Costs shows
  `Skip`.
- **Back keeps the result.** From Spec, `click link "Back"` returns to the same Costs figures.
- **Proof.** `shot` + `snap` of each screen; `net` shows no new `/api` call (both screens render the
  existing result).

## Gotchas

- Both screens only render what Estimates computed; they are wrong exactly when Estimates is. Verify
  maths changes with the backend tests too (`uv run pytest tests/test_costs.py tests/test_spec.py`
  in `backend/`).
- Negative savings ranges print as "−£120–−£42–£35 /yr" (low–central–high); read them carefully.
- Spec is only "done" after a visit; skipping it via the step bar leaves later forward buttons
  missing (see [plan-pack](./plan-pack.md)).
