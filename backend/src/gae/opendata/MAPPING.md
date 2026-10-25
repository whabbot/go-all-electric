# EPC mapping contract

Checked 23 October 2026 against the [official API documentation](https://get-energy-performance-data.communities.gov.uk/api-technical-documentation),
[OpenAPI](https://raw.githubusercontent.com/communitiesuk/epb-data-warehouse/main/api/api.yml)
and [schema samples](https://github.com/communitiesuk/epb-data-warehouse/tree/main/spec/fixtures/json_samples).
The GOV.UK “Get energy performance of buildings data” API is hosted at
`https://api.get-energy-performance-data.communities.gov.uk`. Set `EPC_API_TOKEN` to the bearer
token from your GOV.UK One Login account page; the client sends `Authorization: Bearer ...`.

Search uses `/api/domestic/search?postcode=...`, follows `pagination.nextPage`, and selects the
latest `registrationDate` per UPRN, or normalized full address when UPRN is absent. Ties use
certificate number for deterministic selection. An address selection supplies `certificate_id`
in the JSON body of `POST /api/epc/certificate`; this fetches that exact certificate, not an
arbitrary address match.
A certificate fetched directly can be old; its registration date is returned for display.
The source covers England and Wales only. Postcode search returns `addresses: []` for no records.

`/api/certificate?certificate_number=...` returns `data`, with schema-specific snake_case fields.
RdSAP 21 descriptions are `{value, language}`; earlier versions use strings. Only English
(language `1`) descriptions are mapped. Numeric dwelling enums are decoded through the provider
code table for the exact schema and assessment type, even when dwelling text is present.
Unresolved codes alone cannot establish a house; an explicit House label with an unknown built
form uses the named low-confidence geometry assumption below.
No full certificate, exact home coordinates, photos or bills are persisted by this package.
`raw_summary` is an allowlist of relevant EPC fields, not the complete response.

| Source | Maths input | Mapping | Named low-confidence default / limitation |
| --- | --- | --- | --- |
| `total_floor_area` (number or value object), else `sap_building_parts[].sap_floor_dimensions[].total_floor_area` | `floor_area_m2` | Positive finite square metres; root total takes precedence. Sum distinct part/floor identities, never multiply by storeys; repeated identities must agree; missing/invalid dimensions refuse partial totals | `floor_area_unavailable`: null and no estimate; ask for measured area |
| All available `dwelling_type`, `built_form`, `property_type` labels, including English `{value, language}` objects (codes resolved with schema and assessment type) | `property_type` | Normalize case, whitespace and hyphens/dashes. Semi-detached, detached, end-terrace, mid-terrace house; bungalow takes precedence over attachment form. Generic dwelling text does not hide a specific built form. | `semi_detached_geometry` for missing/unrecorded/unresolved form without an explicit non-house signal; low confidence and explicit survey assumption. `enclosed_terrace_geometry`: enclosed end/mid-terraces use the corresponding ordinary terrace perimeter, low confidence because extra party walls are not modelled. Explicit flat/maisonette/park-home labels or static decoded codes disable Estimate A; a usable bill still supplies Estimate B. RdSAP geometry codes have a static fallback when the codes service cannot resolve them. House type and floor area entered by the homeowner override house geometry, with source “Entered by you”; explicit non-house types remain excluded. |
| Property form | `storeys` | Bungalow: 1; house: 2 | `assumed_storeys`, always low; these are not measured storeys |
| Uniform `sap_building_parts[].construction_age_band`, decoded by `/api/codes/info` with `schemaVersion` and matching `assessmentType` | `year_built` | Closed bands use their start; open-ended bands expose `(null, upper)` or `(lower, null)` in confidence `value_range` and a representative year for maths only. Before/pre-1900 uses an upper bound and representative year of 1899 | `unknown_age_1930` if absent, mixed, undecodable, or code service unavailable; open-ended bands use `open_ended_age_band`, low confidence; representative years are a simplification |
| Uniform `walls[].description` | `wall_type` | Solid brick/no insulation → solid_brick; solid brick/insulation → solid_insulated; cavity/no insulation → cavity_unfilled; cavity/insulated or filled cavity → cavity_filled; timber frame → timber_frame | `unknown_wall_cavity_unfilled` for ambiguous, missing or differing walls; cannot area-weight extensions |
| `windows[].description` (alternative field `window.description`) | `glazing` | Fully single → single; fully double → double_unknown_date; fully triple → triple | `unknown_glazing_double_u_2_8`; fully double also low because date/U-value unknown; mixed glazing not represented |
| Uniform `roofs[].description` | `loft_insulation_mm` | Pitched, explicit N mm loft insulation → N; pitched/no insulation → 0 | `unknown_roof_zero_loft_depth` for flat, mixed, unknown roofs; this is a model assumption, not observed lack of insulation |
| Uniform `floors[].description` | `floor_insulated` | No insulation/uninsulated → false; insulated → true | `unknown_floor_uninsulated`; other premises below and differing floors cannot be represented |
| Uniform `main_heating[].description` | `main_heating_fuel` (metadata) | mains gas, oil, LPG, electric by complete words | `unknown_heating_fuel` → other; fuel is not an argument to `estimate_fabric` |
| Location default | `design_outdoor_temp_c` | -2C | `london_design_minus_2c`, low; not a location-derived design temperature |

Confidence means confidence in the mapping from the EPC, not proof that the EPC still reflects the
home. All recorded fields are medium at best and need confirmation at survey. Every mapping
assumption is returned in `confidence` with source, note and default name. The maths core's own
geometry, air-change and U-value assumptions remain visible in the returned estimate. Do not
present the fabric range without these mapping caveats: its ±15% model range does not quantify
unknown geometry or fabric. Unsupported geometry or missing floor area returns `estimate: null`
and a specific `reason`.

## Geometry diagnosis and photo independence

The provider code table checked on 24 October 2026 contains built forms `Detached`,
`Semi-Detached`, `End-Terrace`, `Mid-Terrace`, `Enclosed End-Terrace`,
`Enclosed Mid-Terrace`, and `Not Recorded`; property types are `House`, `Bungalow`,
`Flat`, `Maisonette`, and `Park home`. Certificates can supply dwelling text directly
or as an English `{value, language}` object. Tests use synthetic records only.

Previously a decoded `House` plus `Not Recorded` (or no built form) triggered the
unsupported-label guard. An unresolved built-form code also refused an otherwise decoded House.
A populated `dwelling_type` masked the other labels and skipped code resolution, so the same
incomplete house description could take a different path depending on where it appeared.
`Semi Detached` also matched the bare `detached` substring, overstating exposed perimeter;
spaced terrace labels could fall through. Enclosed hyphenated terrace labels already matched,
but their geometry approximation was not identified as a low-confidence assumption.

The initial Estimate A is `mapping.estimate` from the EPC alone. Photo uploads are read in
parallel, but neither their count nor their absence changes that mapping or bypasses its
refusal. Boiler/radiator/loft readings do not change the initial fabric numbers; a later,
explicit evidence-review conflict proposal is a separate step. The no-photo regression checks
that a synthetic decoded House with unrecorded form returns Estimate A, and that adding a
boiler photo or one/two radiator photos leaves it identical.

## Weather and bills

[postcodes.io](https://postcodes.io/docs/api/lookup-postcode/) supplies the postcode centroid only.
[Open-Meteo archive](https://open-meteo.com/en/docs/historical-weather-api) supplies
`temperature_2m_mean` in Celsius for inclusive dates in `Europe/London`. These are reanalysis grid
estimates, not a sensor at the house. Daily heating degree days are `max(0, 15.5 - mean_temperature)`;
15.5C is the existing UK convention in the maths constants, allowing for incidental internal and
solar gains. This daily mean approximation is not an hourly integration.

The weather route returns requested dates, days expected/covered, missing-day count, observed
partial sum and `heating_degree_days`. The latter is null when *any* day is missing or invalid.
Duplicate days are invalid, never double counted. No weather is imputed. Dates are restricted to
historical archive data (1940 through yesterday), at most two years per request. Recent days may
still be missing because the archive lags; the result says so. No local design temperature is
claimed: the named -2C London default is returned explicitly with low confidence for all locations.

`measured_from_bill(start, end, gas_kwh, postcode, weather_client=...)` injects the small
`DegreeDayProvider` Protocol, implemented by `WeatherClient`; it fetches the exact period. The
separate `measured_from_degree_days` is pure. Fetching network data cannot itself be pure.
Use inclusive dates spanning a complete calendar year (e.g. July 2023–June 2024, or 15 July–14 July).
Leap days are included. Short bills are rejected rather than annualized. Optional monthly values
are month-number → kWh for all 12 complete calendar months in the same period, totaling the bill
within 1%; partial calendar-month periods must omit this option. The core then derives the summer
baseline, or returns its named baseline-fraction caveat when monthly data is omitted.
Missing or mismatched weather, unavailable postcode, invalid kWh and incomplete periods return
`status: couldnt_tell`, a reason, and no estimate. Network errors never trigger a London weather
fallback. Weather itself is medium confidence; the core's boiler and baseline caveats remain.

Routes are synchronous FastAPI endpoints (run in its thread pool), with 20-second HTTP timeouts,
no automatic retries or redirects, bounded EPC pagination and `Cache-Control: no-store, private`.
Credentials are server-only SecretStr values, never included in public errors or upstream bodies.
Applications should avoid recording query strings containing postcodes in access logs.
