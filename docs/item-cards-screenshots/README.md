# Radiator cards and "Add details you know": verification screenshots

Captured with the `verify-go-all-electric` skill in **mock** mode (offline demo data: Sam's sample
house and synthetic images only; mock photo checks and readings are canned, so these prove the UI
wiring, not Gemini). `390-*` is the 390x844 phone harness, `desk-*` is 1280x800.

- `*-01..05`: three radiators added one card at a time: radiator 1 with two photos (read as one
  radiator), radiator 2 with entered details only, radiator 3 with one photo; room labels; boiler
  details entered next to a boiler photo.
- `*-07`, `*-08`: "What we read": radiators by number and label, "(you)" on entered values, and the
  boiler's entered model and output shown against the photo reading instead of picking one silently.
- `*-09`: the Spec radiator check named "Radiator N · label".
- `after-*`: walk items 9-11 from PR #43 (before: `docs/verify-walkthrough-screenshots/f03`, `f05`,
  `f11`): Cancel all / Skip this photo in the Redact dialog, the over-limit notice clearing once the
  queue is done, Replace photo with one verdict, the ratio range kept on one line, and an empty
  postcode field after loading Sam's sample.
