import type { PhotoKind } from '../api'

/** Keys for “why we need this” copy — capture photos, radiator video, installer quotes. */
export type WhyNeedId = PhotoKind | 'radiator_video' | 'installer_quotes'

export type WhyNeedContent = {
  dialogTitle: string
  bullets: string[]
  privacy: string
}

/**
 * Plain-English reasons grounded in backend survey/analysis, heatpump, plan, gemini checks.
 * Keep in sync with code paths — do not claim uses that are only photo checks with no maths effect.
 */
export const WHY_NEED: Record<WhyNeedId, WhyNeedContent> = {
  boiler_plate: {
    dialogTitle: 'Why we need the boiler data plate',
    bullets: [
      'We read make, model and central-heating output (kW) from the plate, and check the model against our boiler datasheet library.',
      'That confirms heating fuel for the Boiler Upgrade Scheme grant (gas from the plate when the EPC is unclear).',
      'The plate kW is not used for Estimate B or heat-pump sizing; measured heat comes from your gas bill when you add one.',
      'If you skip it, we rely on the EPC heating description for fuel and grant eligibility, with lower confidence.',
    ],
    privacy:
      'Only your redacted JPEG leaves the device; we keep extracted readings (not the image). Saved surveys store postcode district only, not your address.',
  },
  radiators: {
    dialogTitle: 'Why we need radiator photos',
    bullets: [
      'Add each radiator (up to 8) and take a photo of it from a front corner, standing and looking down at about 45° so the front face, top grille/convector fins and one end are visible, with a tape measure held across the width.',
      'We read each radiator’s type (counting panels and fin rows from the angled view), take width from the tape measure, estimate height from the visible proportion with the end view, and rate output at ΔT50 from typical catalogue figures.',
      'Each radiator is checked at the 45°C target flow temperature and shown on your target spec and in the verification log.',
      'If you skip it (and skip the walkthrough video), we cannot flag radiator upsizing; flow temperature and grant still come from your estimates.',
    ],
    privacy:
      'Only your redacted JPEGs are sent for analysis; we store readings only. Postcode district only is saved — never the photos.',
  },
  fuse_cutout: {
    dialogTitle: 'Why we need the fuse cutout',
    bullets: [
      'We read the main service fuse rating in amps from the sealed cutout (not the meter or consumer unit).',
      'That rating drives the all-electric plan “Electricity supply” step: headroom for the heat pump and whether a typical home EV charger still fits on the same fuse.',
      'Without it, supply status is “couldn’t tell” and EV charger advice waits until you photograph the fuse label.',
      'Skipping it does not change Estimate A/B or heat-pump kW sizing — only supply and charger feasibility flags.',
    ],
    privacy:
      'Only the redacted cutout photo is sent; we keep the amp rating as a reading. No image is stored in your saved survey.',
  },
  outdoor_space: {
    dialogTitle: 'Why we need an outdoor unit spot photo',
    bullets: [
      'We estimate clear width and depth (metres), surface type and nearby obstructions for the proposed heat-pump location.',
      'Code checks whether a typical monobloc unit (~1.0 × 0.6 m) likely fits; warnings stay on the reading if space looks tight.',
      'This does not change heat-pump kW sizing, running-cost maths or the all-electric plan steps — it is shown on your survey as “whether an outdoor unit fits”.',
      'Optional: skip it if you will confirm siting with your installer; we will not guess a location.',
    ],
    privacy:
      'Only your redacted photo is analysed; dimensions and notes are kept as readings, not the image. Location in saves is postcode district only.',
  },
  loft: {
    dialogTitle: 'Why we need a loft photo',
    bullets: [
      'We check whether loft insulation is visible, whether ceiling joists show above the wool, and estimate the depth band (0 to 270 mm+).',
      'EPC loft insulation depth is often out of date; in the one-context review, Gemini 4 Argon can cite this photo to propose a corrected depth so code can re-run Estimate A and test whether it explains the gap with your bills.',
      'The loft reading is not fed directly into Estimate A — headline fabric numbers stay on the EPC until code tests a conflict proposal.',
      'Optional: skip it if you cannot safely look through the hatch; we will not guess loft depth.',
    ],
    privacy:
      'Only your redacted JPEG is analysed; we store the extracted depth band and notes as a reading, never the photo. Location in saved surveys is postcode district only.',
  },
  gas_bill: {
    dialogTitle: 'Why we need a gas bill',
    bullets: [
      'We read gas used in kWh and the billing period (and month-by-month kWh when shown) — not £ or m³.',
      'With your house postcode we fetch heating degree days for those exact dates, then compute Estimate B (measured design heat loss), compare it to the EPC fabric estimate, and annual gas vs heat-pump running costs.',
      'A good bill also sizes installer quotes against your measured target kW range; without it sizing falls back to the fabric estimate only.',
      'If you skip it, you get fabric-based sizing only, no A-vs-B cross-check, and quote size flags are limited to flow temperature, buffer tank and grant.',
    ],
    privacy:
      'Redact name, address, account and meter numbers before upload (same as other photos). We send the redacted image once; stored surveys keep kWh and dates as readings, postcode district only.',
  },
  radiator_video: {
    dialogTitle: 'Why we might film radiators',
    bullets: [
      'The walkthrough counts distinct radiators and reads type and size per radiator (same 45°C upsizing check as a single photo, applied to each legible radiator).',
      'Uncertain radiators become photo requests on the capture screen — never guessed sizes.',
      'Video does not replace a gas bill for Estimate B; it adds radiator checks when photographing every radiator is awkward.',
      'If you skip it, add one 45° front-corner photo per radiator instead, or leave radiators out and accept no upsizing flags.',
    ],
    privacy:
      'Video is not blacked out like photos — film radiators only, close. Container metadata is stripped server-side before analysis; video is not stored. Readings only are kept if you run estimates.',
  },
  installer_quotes: {
    dialogTitle: 'Why we need installer quotes',
    bullets: [
      'We read quoted heat-pump kW, design flow temperature, MCS heat loss if stated, buffer tank mention, and whether the BUS grant is deducted.',
      'Code flags oversizing vs your measured target range (when you have Estimate B), high flow temperatures, buffer tanks, and missing grant deductions — plus questions to ask the installer.',
      'Without a usable bill, kW is not size-checked; flow, buffer and grant checks still run.',
      'Quotes are optional; they are prompts for your conversations, not sent to installers or MCS.',
    ],
    privacy:
      'PDFs are rendered and redacted on your device; only redacted JPEG pages are sent. We label quotes “Quote A/B/C”, not your file names, and do not store quote documents.',
  },
}
