import type {
  Disagreement,
  EnteredValueScalar,
  InputReading,
  KnownBoiler,
  KnownFuse,
  KnownRadiator,
  RadiatorKind,
} from '../api/types'

/** Room pick list for labelling a radiator. Labels stay in this browser tab only. */
export const RADIATOR_ROOMS = [
  'Living room',
  'Dining room',
  'Kitchen',
  'Hall',
  'Landing',
  'Main bedroom',
  'Bedroom',
  'Bathroom',
  'Study',
  'Utility room',
  'Conservatory',
] as const

export const RADIATOR_NOTE_MAX = 30

/** Plain-language radiator types, in the reading schema's codes. */
export const RADIATOR_TYPE_OPTIONS: { value: RadiatorKind; label: string; hint: string }[] = [
  { value: 'single_panel', label: 'Single panel, no fins', hint: 'One flat panel, nothing behind it (Type 10)' },
  { value: 'K1', label: 'Single panel with fins', hint: 'One panel with zig-zag fins behind it (Type 11, K1)' },
  { value: 'P+', label: 'Double panel, one set of fins', hint: 'Two panels with one row of fins between (Type 21, P+)' },
  { value: 'K2', label: 'Double panel, two sets of fins', hint: 'Two panels, each with fins (Type 22, K2)' },
  { value: 'K3', label: 'Triple panel', hint: 'Three panels with fins (Type 33, K3)' },
  { value: 'column', label: 'Column radiator', hint: 'Upright tubes or columns, often cast iron' },
  { value: 'towel_rail', label: 'Towel rail', hint: 'Ladder-style rail, usually in a bathroom' },
  { value: 'other', label: 'Something else', hint: "Not one of these, or you're not sure" },
]

/** Panels and fin rows each panel type has (matches the backend's checks). */
export const RADIATOR_SHAPES: Partial<Record<RadiatorKind, [number, number]>> = {
  single_panel: [1, 0],
  K1: [1, 1],
  'P+': [2, 1],
  K2: [2, 2],
  K3: [3, 3],
}

/** Main service fuse ratings fitted in UK homes. */
export const FUSE_RATINGS_A = [40, 45, 60, 63, 80, 100]

/** What the homeowner typed, as text, so half-typed values survive collapsing a card. */
export type DetailInputs = Record<string, string>

type NumberRule = { min: number; max: number; integer: boolean; unit: string }

const NUMBER_RULES: Record<string, NumberRule> = {
  panels: { min: 1, max: 3, integer: true, unit: '' },
  fin_rows: { min: 0, max: 3, integer: true, unit: '' },
  width_mm: { min: 300, max: 3000, integer: true, unit: ' mm' },
  height_mm: { min: 250, max: 2000, integer: true, unit: ' mm' },
  heating_output_kw: { min: 3, max: 70, integer: false, unit: ' kW' },
  hot_water_output_kw: { min: 3, max: 70, integer: false, unit: ' kW' },
}

const POSTCODE = /\b[A-Z]{1,2}[0-9][A-Z0-9]?\s*[0-9][A-Z]{2}\b/i

type Parsed<T> = { known: T; errors: Record<string, string> }

function parseNumbers(inputs: DetailInputs, fields: string[], out: Record<string, unknown>, errors: Record<string, string>) {
  for (const field of fields) {
    const raw = (inputs[field] ?? '').trim()
    if (!raw) continue
    const rule = NUMBER_RULES[field]
    const value = Number(raw)
    if (!Number.isFinite(value) || (rule.integer && !Number.isInteger(value))) {
      errors[field] = rule.integer ? 'Enter a whole number.' : 'Enter a number.'
    } else if (value < rule.min || value > rule.max) {
      errors[field] = `Enter ${rule.min}–${rule.max}${rule.unit}.`
    } else {
      out[field] = value
    }
  }
}

export function parseKnownRadiator(inputs: DetailInputs): Parsed<KnownRadiator> {
  const known: KnownRadiator = {}
  const errors: Record<string, string> = {}
  const type = inputs.radiator_type as RadiatorKind | undefined
  if (type && RADIATOR_TYPE_OPTIONS.some((o) => o.value === type)) known.radiator_type = type
  parseNumbers(inputs, ['panels', 'fin_rows', 'width_mm', 'height_mm'], known, errors)
  const shape = known.radiator_type ? RADIATOR_SHAPES[known.radiator_type] : undefined
  if (shape) {
    const [panels, fins] = shape
    if (known.panels != null && known.panels !== panels) {
      errors.panels = `This type has ${panels} panel${panels === 1 ? '' : 's'}.`
      delete known.panels
    }
    if (known.fin_rows != null && known.fin_rows !== fins) {
      errors.fin_rows = `This type has ${fins} fin row${fins === 1 ? '' : 's'}.`
      delete known.fin_rows
    }
  }
  return { known, errors }
}

export function parseKnownBoiler(inputs: DetailInputs): Parsed<KnownBoiler> {
  const known: KnownBoiler = {}
  const errors: Record<string, string> = {}
  for (const [field, max] of [
    ['make', 40],
    ['model', 60],
  ] as const) {
    const value = (inputs[field] ?? '').split(/\s+/).filter(Boolean).join(' ')
    if (!value) continue
    if (value.length > max) errors[field] = `Keep it to ${max} characters.`
    else if (POSTCODE.test(value)) errors[field] = 'Enter the make or model only.'
    else known[field] = value
  }
  parseNumbers(inputs, ['heating_output_kw', 'hot_water_output_kw'], known, errors)
  return { known, errors }
}

export function parseKnownFuse(inputs: DetailInputs): Parsed<KnownFuse> {
  const value = Number(inputs.rating_a)
  return { known: FUSE_RATINGS_A.includes(value) ? { rating_a: value } : {}, errors: {} }
}

export function hasEntries(known: object): boolean {
  return Object.keys(known).length > 0
}

/** "Bedroom – back" for display; null when nothing was picked or typed. */
export function radiatorLabel(room: string, note: string): string | null {
  const n = note.trim()
  if (room && n) return `${room} – ${n}`
  return room || n || null
}

/** How a radiator is shown: the homeowner's label, else the room Gemini saw, else its number. */
export function radiatorName(
  index: number,
  labels: (string | null)[],
  readings: InputReading[],
): string {
  const number = `Radiator ${index + 1}`
  const label = labels[index]
  if (label) return `${number} · ${label}`
  const reading = readings.find((r) => r.kind === 'radiators' && r.index === index)?.reading
  const room = typeof reading?.room === 'string' ? reading.room.trim() : ''
  return room ? `${number} · ${room}` : number
}

/** Spec rooms come back as "Radiator N"; show them with the homeowner's label. */
export function specRoomName(room: string, labels: (string | null)[], readings: InputReading[]): string {
  const match = /^Radiator (\d+)$/.exec(room)
  return match ? radiatorName(Number(match[1]) - 1, labels, readings) : room
}

const TOLERANCE: Record<string, number> = {
  total_kwh: 0.05,
  width_mm: 0.1,
  height_mm: 0.1,
  heating_output_kw: 0.05,
  hot_water_output_kw: 0.05,
}

function agrees(field: string, entered: EnteredValueScalar, read: EnteredValueScalar): boolean {
  if (typeof entered === 'string' && typeof read === 'string') {
    const [a, b] = [entered, read].map((v) => v.toLowerCase().replaceAll('-', ' ').split(/\s+/).filter(Boolean).join(' '))
    return field === 'make' || field === 'model' ? a.includes(b) || b.includes(a) : a === b
  }
  if (typeof entered === 'number' && typeof read === 'number') {
    return Math.abs(entered - read) <= (TOLERANCE[field] ?? 0) * Math.abs(entered)
  }
  return entered === read
}

/** Mirror of the backend's merge, for offline demo data: entered values win, disagreements kept. */
export function applyEntered(
  reading: Record<string, unknown>,
  entered: Record<string, EnteredValueScalar>,
): { reading: Record<string, unknown>; disagreements: Disagreement[] } {
  const disagreements: Disagreement[] = []
  for (const [field, value] of Object.entries(entered)) {
    const read = reading[field]
    if ((typeof read === 'string' || typeof read === 'number') && !agrees(field, value, read)) {
      disagreements.push({ field, entered: value, read })
    }
  }
  return { reading: { ...reading, ...entered }, disagreements }
}

const FIELD_LABELS: Record<string, string> = {
  radiator_type: 'type',
  panels: 'panels',
  fin_rows: 'fin rows',
  width_mm: 'width',
  height_mm: 'height',
  make: 'make',
  model: 'model',
  heating_output_kw: 'heating output',
  hot_water_output_kw: 'hot-water output',
  rating_a: 'fuse rating',
}

const FIELD_UNITS: Record<string, string> = {
  width_mm: ' mm',
  height_mm: ' mm',
  heating_output_kw: ' kW',
  hot_water_output_kw: ' kW',
  rating_a: ' A',
}

export function fieldLabel(field: string): string {
  return FIELD_LABELS[field] ?? field.replaceAll('_', ' ')
}

export function formatField(field: string, value: unknown): string {
  if (field === 'radiator_type') {
    const option = RADIATOR_TYPE_OPTIONS.find((o) => o.value === value)
    if (option) return option.label.toLowerCase()
  }
  const unit = FIELD_UNITS[field] ?? ''
  return typeof value === 'number' ? `${value.toLocaleString('en-GB')}${unit}` : `${String(value)}${unit}`
}
