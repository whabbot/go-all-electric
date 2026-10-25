# Start and property lookup

Start lets a homeowner find their house by postcode from the EPC register, pick it from a list, and
continue into the flow; once a house is picked the app shows only the postcode district ("house in
N10"). In mock mode a "Load Sam's sample (demo)" button loads the demo house and unlocks every step.

## Sub-features

- `start-details` offers House type and Floor area (m²) under Add details you know; entries show (you), override house geometry and make old results stale. Explicit flats still use bills only.
- `start-search` searches EPC records for a postcode and lists addresses with band and date.
- `start-no-results` shows "Could not find EPC records" with Try again (and Use Sam's sample in
  mock).
- `start-pick` picks a house; the address list and postcode disappear and only the district shows.
- `start-change` "Choose a different house" clears the pick.
- `start-sample` mock only: "Load Sam's sample (demo)" picks Sam's house and unlocks all steps.
- `start-gate` steps after Start stay locked (shown "(after <step>)") until Start is complete; a
  deep link to a locked step lands on the furthest reachable one.

## How to get to it (user POV)

- Open the app at `/` (first screen, step 1/8).
- Step bar link `Start` or `Back` from Photos.

## Driving it with drive.sh

Preconditions:

- Mock: fresh `frame 390 844 /`. The postcode field is prefilled with `N10 2AB`.
- Real: fresh frame plus the private postcode file for `realhouse`. Never type a real postcode by
  hand into a command, and take no screenshot while a postcode or address list is on screen.

- **No results.** Enter a too-short postcode. `fill Postcode "ZZ1"`, `click button "Find EPC"`. An
  alert "Could not find EPC records" says "No EPC records found — try a full postcode." with
  `Try again` and (mock) `Use Sam's sample`.
- **Search.** `fill Postcode "N10 2AB"`, `click button "Find EPC"`. Buttons
  `14 Oakwood Avenue, London ...` and `16 Oakwood Avenue, London ...` appear, each with an EPC band
  and registration date.
- **Pick.** `click button "14 Oakwood"`. The list and postcode clear; "Selected: house in N10 · EPC
  band D" and "From here on we show the postcode district only." appear with
  `Choose a different house`. The step bar shows `Photos` as reachable.
- **Continue.** `click link "Continue"`. `where` prints `/capture`; Photos shows "house in N10".
- **Change house.** Back on Start, `click button "Choose a different house"`. The selection clears
  and the search field is usable again.
- **Sample (mock).** Fresh frame, `click button "Load Sam's sample (demo)"`. All eight step links
  become reachable (`fjs 'return [...d.querySelectorAll(".flow-steps a")].length'` prints 8).
- **Locked deep link.** Fresh `frame 390 844 /pack`. `where` prints the furthest reachable step
  (`/capture` in mock, `/` in real with no house), not `/pack`.
- **Real mode.** `realhouse` prints `Selected: house in <district>`. Then `click link "Continue"`.
- **Known details.** After Pick, `click summary "Add details you know"`; choose House type and fill Floor area (m²). Continue through Photos then `Next: Estimates` to get estimates. Return to Start, change either entry, then visit Estimates: the stale-results banner appears.
- **Proof.** `shot` + `snap` after Pick (district only) and after Continue.

## Gotchas

- Mock mode counts Start as complete without a pick ("using the demo home for now" on Photos), so
  `Continue` is always there. Real mode needs a picked house before any later step unlocks.
- Mock search matches on the first four characters of the postcode (anything starting `N10 2` finds
  Sam's houses); under five characters returns nothing.
- Flats are refused by design in real mode; pick a house.
- "Load Sam's sample (demo)" clears the postcode input; only the district is shown after selection.
- The live site has an access-code screen; local real mode does not (no `ACCESS_CODE_HASH`). Do not
  test sign-in against the deployed site.
