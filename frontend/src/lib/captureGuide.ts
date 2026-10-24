import type { PhotoKind } from '../api'

export type CaptureNeedStatus = 'most_important' | 'optional' | 'recommended'

export type CaptureSummaryItem = {
  id: string
  label: string
  status: CaptureNeedStatus
  /** One-line checklist emphasis (e.g. why gas bill matters most). */
  reason?: string
  photoCount: string
  timeHint: string
}

/** Top-of-screen checklist — grounded in backend slots and analysis behaviour. */
export const CAPTURE_SUMMARY_ITEMS: CaptureSummaryItem[] = [
  {
    id: 'gas_bill',
    label: 'Gas bill',
    status: 'most_important',
    reason: 'Drives your measured heat loss, running costs and the quote size check.',
    photoCount: '1 photo or screenshot',
    timeHint: 'about 2 min',
  },
  {
    id: 'loft',
    label: 'Loft',
    status: 'recommended',
    photoCount: '1 photo',
    timeHint: 'about 2 min',
  },
  {
    id: 'boiler_plate',
    label: 'Boiler data plate',
    status: 'recommended',
    photoCount: '1 photo',
    timeHint: 'about 1 min',
  },
  {
    id: 'radiators',
    label: 'Radiators',
    status: 'recommended',
    photoCount: '1 photo, or film a walkthrough instead',
    timeHint: 'about 2 min',
  },
  {
    id: 'fuse_cutout',
    label: 'Fuse cutout',
    status: 'recommended',
    photoCount: '1 photo',
    timeHint: 'about 1 min',
  },
  {
    id: 'outdoor_space',
    label: 'Outdoor unit spot',
    status: 'optional',
    photoCount: '1 photo',
    timeHint: 'about 1 min',
  },
]

export const CAPTURE_STATUS_LABEL: Record<CaptureNeedStatus, string> = {
  most_important: 'Most important',
  optional: 'Optional',
  recommended: 'Recommended',
}

export type CaptureItemGuidance = {
  oneLine: string
  detail?: string
  goodReason: string
  badReason: string
}

export const CAPTURE_GUIDANCE: Record<PhotoKind, CaptureItemGuidance> = {
  boiler_plate: {
    oneLine:
      'Straight-on, sharp photo of the data plate: make, model and central-heating output (kW) must be readable.',
    goodReason: 'Plate fills the frame, sharp, and kW figure is visible.',
    badReason: 'Too far, blurry, glare, or cropped so make/model/kW are missing.',
  },
  radiators: {
    oneLine:
      'Whole radiator from the front with scale (tape measure helps). Or use the walkthrough video instead of a photo.',
    detail:
      'Video: radiators only, up to 90 seconds and 100 MB; metadata is stripped but video is not blacked out like photos.',
    goodReason: 'Full radiator in frame with clear edges and scale.',
    badReason: 'Cropped, too far, or glare hides type and size.',
  },
  fuse_cutout: {
    oneLine:
      'The sealed service fuse carrier (not the meter or consumer unit): amp rating (e.g. 60, 80, 100) readable.',
    goodReason: 'Cutout close-up with the amp number legible.',
    badReason: 'Wrong subject (meter or consumer unit), blurry, or rating not visible.',
  },
  outdoor_space: {
    oneLine:
      'The proposed heat-pump spot from a few steps back: wall, ground and nearby windows in frame; tape measure helps.',
    goodReason: 'Clear width and depth with scale and obstructions visible.',
    badReason: 'Too tight, no scale, or key obstructions out of frame.',
  },
  loft: {
    oneLine:
      'From the hatch with your torch on, showing the insulation and ceiling joists; a tape measure pushed into the wool helps.',
    goodReason: 'Insulation and joists (or a tape measure in the wool) are clearly lit and in focus.',
    badReason: 'Too dark, hatch closed, or only boarding and boxes visible so insulation depth cannot be judged.',
  },
  gas_bill: {
    oneLine:
      'UK bill or annual statement showing gas used in kWh (not £ or m³) and period start/end dates.',
    detail:
      'Best: about 10–14 months of usage (roughly a full year) — an annual statement or 12-month graph from your supplier app. ' +
      'Shorter periods still work: we use your exact dates for weather, but a partial year shows a warning and annualising one month is less reliable (a single winter or summer month can look too high or low). ' +
      'Before upload, black out your name, address, account and meter numbers (same cover-up step as other photos).',
    goodReason: 'Usage panel shows kWh and date range, sharp and uncropped.',
    badReason: 'Only charges in £, dates or kWh missing, blurry, or personal details left visible.',
  },
}
