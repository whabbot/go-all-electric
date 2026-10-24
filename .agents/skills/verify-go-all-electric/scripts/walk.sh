#!/usr/bin/env bash
# Mock-mode smoke walk: screenshot every guided-flow step at phone width (390x844, p*) and on a
# projector-sized page (1280x800, d*), with audit JSON for the main screens.
#
#   walk.sh [NAME]        # evidence goes to .verify/evidence/<date>-NAME (default: walk)
#
# It is a regression net for layout and step wiring, not a proof of any one feature: it drives
# the happy path only. When a label below is renamed, the step prints MISSING <label>; fix the
# label here and in features/.
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/drive.sh"
[ "${GAE_MODE:-}" = mock ] || { echo "walk.sh: needs a mock-mode instance (launch.sh mock)"; exit 1; }
evidence "${1:-walk}" >/dev/null

phone() {
  frame 390 844 /
  shot p01-start; audit >"$EV/p01.json"
  fill Postcode "ZZ1"; click button "Find EPC"; sleep 0.8; shot p02-start-no-results
  fill Postcode "N10 2AB"; click button "Find EPC"; sleep 0.8; shot p03-start-results
  click button "14 Oakwood"; shot p04-start-selected
  click link "Continue"; shot p05-photos; audit >"$EV/p05.json"; shot p05-photos-full full
  click button "Boiler data plate"; click button "See examples"; shot p06-examples; click button "Close"
  upload "Boiler data plate"; shot p07-redact; blackout; shot p07-redact-box
  click button "Use photo"; into '.capture-slot-accordion--checking'; shot p08-checking
  sleep 1.6; shot p09-checked
  upload "Radiators" 3; shot p10-radiators-1of3
  click button "Use photo"; click button "Cancel"; click button "Use photo"; sleep 1.6
  into '.radiator-list'; shot p11-radiators-list
  upload "Gas bill"; click button "Use photo"; sleep 1.6
  click link "Next: Estimates"; sleep 0.3; shot p12-estimates-running
  waitfor "Next: Costs" 30; shot p13-estimates; audit >"$EV/p13.json"; shot p13-estimates-full full
  click button "Ask Gemini to review everything"; sleep 1; into '.review-panel'; shot p14-review-thinking
  waitfor "Why the estimates differ" 30; into '.review-panel'; shot p15-review-done
  click link "Next: Costs"; shot p16-costs; audit >"$EV/p16.json"; shot p16-costs-full full
  click link "Next: Spec"; shot p17-spec; shot p17-spec-full full
  click link "Next: Quotes"; shot p18-quotes-empty
  click button "Load Sam's three quotes"; sleep 0.3; shot p19-quotes-checking
  waitfor "Questions to ask before signing" 20; into '.quote-card'; shot p20-quotes; shot p20-quotes-full full
  click link "Next: Plan"; shot p21-plan; audit >"$EV/p21.json"; shot p21-plan-full full
  click link "Next: Pack"; shot p22-pack; audit >"$EV/p22.json"
  click button "Draft"; sleep 0.5; shot p23-pack-drafting
  waitfor "drafted by" 30; shot p24-pack-drafted; shot p24-pack-full full
}

projector() {
  desk /
  shot d01-start; audit >"$EV/d01.json"
  click button "Load Sam's sample (demo)"; click link "Continue"; shot d02-photos
  click link "Next: Estimates"; waitfor "Next: Costs" 30; shot d03-estimates; audit >"$EV/d03.json"
  click link "Next: Costs"; shot d04-costs
  click link "Next: Spec"; shot d05-spec
  click link "Next: Quotes"; click button "Load Sam's three quotes"; waitfor "Questions to ask before signing" 20; shot d06-quotes
  click link "Next: Plan"; shot d07-plan
  click link "Next: Pack"; shot d08-pack
}

phone
projector
echo "walk: done; $(ls "$EV"/*.png | wc -l | tr -d ' ') screenshots in $EV"
