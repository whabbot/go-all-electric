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
    photoCount: 'Bill photos or typed usage',
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
    photoCount: 'Add each radiator: a photo or two, or details you know',
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

export function captureSummaryForKind(kind: PhotoKind): CaptureSummaryItem {
  const item = CAPTURE_SUMMARY_ITEMS.find((i) => i.id === kind)
  if (!item) {
    throw new Error(`No capture summary for ${kind}`)
  }
  return item
}

/** First checklist slot still missing a photo or entered details (radiators may use video instead). */
export function firstCaptureSlotNeedingAttention(
  photos: { kind: PhotoKind; fileName: string | null; entered?: boolean }[],
  radiatorVideo: File | null,
): PhotoKind | null {
  for (const item of CAPTURE_SUMMARY_ITEMS) {
    const kind = item.id as PhotoKind
    const slot = photos.find((p) => p.kind === kind)
    if (!slot || slot.entered) continue
    if (kind === 'radiators') {
      if (!slot.fileName && !radiatorVideo) return kind
    } else if (!slot.fileName) {
      return kind
    }
  }
  return null
}

export const CAPTURE_CHECKLIST_HEADING = "What you'll need"
export const CAPTURE_CHECKLIST_INTRO = `${CAPTURE_SUMMARY_ITEMS.length} capture steps · about 5–10 minutes total. Each photo is checked after you redact anything identifying.`

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
      'One shot per radiator from a front corner, standing and looking down at about 45°, so the front face, top grille/fins and one end are visible, with a tape measure held across the width — or use the walkthrough video instead.',
    detail:
      'Press Add radiator for each radiator (up to 8) and label its room. Two or three photos of the same radiator are read together as that one radiator. Know its type or size? Add the details instead of, or as well as, a photo. Or film a walkthrough video instead: radiators only, up to 90 seconds and 100 MB; metadata is stripped but video is not blacked out like photos.',
    goodReason:
      'Taken from a front corner looking down at ~45° so the front face, top grille/fins and end are all visible, with a tape measure held across the width.',
    badReason:
      'Straight front-on (single and double panel radiators look alike from the front, so type cannot be told), cropped, or no scale.',
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
      '12 months in a row gives the best estimate, but any bills or typed periods help. ' +
      'Add several bill photos, or type gas kWh and dates under “Add details you know”. Gaps are OK; short coverage widens the estimate and annual Costs are estimated. ' +
      'Before upload, black out your name, address, account and meter numbers (same cover-up step as other photos).',
    goodReason: 'Usage panel shows kWh and date range, sharp and uncropped.',
    badReason: 'Only charges in £, dates or kWh missing, blurry, or personal details left visible.',
  },
}
