/** Offline demo data: Sam's invented 1930s semi. The UI labels mock mode wherever it is shown. */
import type {
  AllElectricPlan,
  AnalysisBundle,
  AnalysisEvent,
  AnalysisResult,
  CostComparison,
  EpcAddress,
  InputReading,
  PhotoCheckResult,
  PhotoKind,
  QuoteCheckResult,
  RadiatorVideoResult,
  ReviewResult,
  VerificationLogEntry,
  VerifiedReading,
} from './types'

const r = (low: number, central: number, high: number) => ({ low, central, high })

export const SAM_EPC_ADDRESSES: EpcAddress[] = [
  {
    certificate_id: '0000-0000-0000-0000-0014',
    address: '14 Oakwood Avenue, London',
    postcode: 'N10 2AB',
    registration_date: '2019-03-14',
    current_energy_efficiency_band: 'D',
  },
  {
    certificate_id: '0000-0000-0000-0000-0016',
    address: '16 Oakwood Avenue, London',
    postcode: 'N10 2AB',
    registration_date: '2021-07-02',
    current_energy_efficiency_band: 'D',
  },
]

export const SAM_ANALYSIS: AnalysisBundle = {
  measured: {
    heating_gas_kwh: r(9360, 11700, 14040),
    baseline_gas_kwh: r(240, 300, 360),
    boiler_efficiency: 0.88,
    htc_w_per_k: r(208.5, 262.4, 318.6),
    design_load_kw: r(3.73, 4.72, 5.73),
    indoor_temp_c: 21,
    design_outdoor_temp_c: -2,
    caveats: [],
  },
  fabric: {
    element_w_per_k: {
      walls: 95.2,
      windows: 42.1,
      doors: 4.8,
      roof: 28.6,
      floor: 18.4,
      thermal_bridging: 12.1,
      ventilation: 38.9,
    },
    htc_w_per_k: r(208.1, 239.9, 271.6),
    design_load_kw: r(7.43, 8.75, 10.06),
    assumptions: [
      {
        default: 'installer_air_change_rate',
        value: 1.5,
        unit: 'ACH',
        note: 'Pre-2000 semi; no air-test data',
      },
      {
        default: 'double_glazing_u_2_8',
        value: 2.8,
        unit: 'W/m²K',
        note: 'Double glazing, install date unknown',
      },
      {
        default: 'wall_u_as_built',
        value: 1.6,
        unit: 'W/m²K',
        note: 'Cavity wall, as built, unfilled',
      },
    ],
    wall_type: 'cavity_unfilled',
    glazing: 'double_unknown_date',
    loft_insulation_mm: 100,
    net_wall_area_m2: 59.5,
    window_area_m2: 15.0,
    roof_area_m2: 45.0,
    volume_m3: 243.0,
    air_change_rate: 1.5,
    built_before_2000: true,
  },
  cross_check: {
    verdict: 'fabric_higher',
    ratio: r(1.30, 1.85, 2.69),
    gap_w_per_k: 175.0,
    reasons: [
      {
        code: 'missed_insulation',
        explanation:
          'Cavity walls may have been filled since the EPC was lodged; unfilled cavity U-values read high.',
        drivers: ['wall_type', 'net_wall_area_m2'],
        potential_w_per_k: 82.0,
        share_of_gap: 0.47,
      },
      {
        code: 'default_air_change_rate',
        explanation:
          'Fabric calc assumes 1.5 air changes/hour (installer default for pre-2000 homes). Your bills may reflect tighter draught-proofing.',
        drivers: ['air_change_rate', 'volume_m3'],
        potential_w_per_k: 59.4,
        share_of_gap: 0.34,
      },
      {
        code: 'sunny_or_part_heated',
        explanation:
          'South-facing rooms or rooms left unheated can make gas use look lower than true heat loss.',
        drivers: ['heating_gas_kwh'],
        potential_w_per_k: 30.8,
        share_of_gap: 0.18,
      },
      {
        code: 'default_glazing_u',
        explanation:
          'U=2.8 for double glazing of unknown age is conservative; newer units would lower fabric loss.',
        drivers: ['glazing', 'window_area_m2'],
        potential_w_per_k: 9.7,
        share_of_gap: 0.06,
      },
    ],
  },
  costs_by_flow_temp: [40, 45, 50, 55].map((flow) => costAtFlow(flow)),
  target_spec: {
    size_kw: r(5.0, 6.0, 7.0),
    max_flow_temp_c: { value: 45, confidence: 'medium' },
    flow_temp_needed_by_current_radiators_c: { value: 52, confidence: 'low' },
    radiators: [
      {
        room: 'Living room',
        flow_temp_c: 45,
        output_w: 2100,
        heat_loss_w: 2400,
        status: 'upsize',
        required_output_dt50_w: 2800,
        min_flow_temp_c: 52,
      },
      {
        room: 'Kitchen',
        flow_temp_c: 45,
        output_w: 1200,
        heat_loss_w: 1100,
        status: 'ok',
        required_output_dt50_w: 980,
        min_flow_temp_c: 38,
      },
      {
        room: 'Main bedroom',
        flow_temp_c: 45,
        output_w: 1400,
        heat_loss_w: 1500,
        status: 'marginal',
        required_output_dt50_w: 1650,
        min_flow_temp_c: 48,
      },
    ],
    grant: {
      amount_gbp: { value: 7500, confidence: 'high' },
      fuel: 'gas',
      note: 'Boiler Upgrade Scheme grant when replacing a gas boiler (illustrative eligibility).',
    },
  },
}

function costAtFlow(flow: number): CostComparison {
  const savings: Record<number, [number, number, number]> = {
    40: [84, 177, 249],
    45: [20, 95, 165],
    50: [-120, -42, 35],
    55: [-433, -179, -12],
  }
  const [low, central, high] = savings[flow] ?? [0, 0, 0]
  const scopCentral = 3.8 - (flow - 40) * 0.03
  return {
    design_flow_temp_c: flow,
    space_heat_kwh: 11700,
    hot_water_heat_kwh: 1800,
    space_heating_scop: r(scopCentral - 0.25, scopCentral, scopCentral + 0.25),
    gas_cost_gbp: { value: 1124, confidence: 'high' },
    heat_pump_cost_gbp: r(1124 - high, 1124 - central, 1124 - low),
    annual_saving_gbp: r(low, central, high),
    break_even_scop: { value: 3.35, confidence: 'medium' },
    break_even_flow_temp_c: r(43.2, 48.3, 54.4),
    prices: {
      electricity_pence_per_kwh: 26.32,
      gas_pence_per_kwh: 7.97,
      period: 'Oct–Dec 2026 price cap',
    },
  }
}

type PhotoMock = Omit<PhotoCheckResult, 'expected_kind' | 'matches_expected' | 'usable' | 'model' | 'elapsed_ms'>

const PHOTO_MOCKS: Record<PhotoKind, PhotoMock> = {
  boiler_plate: {
    kind: 'boiler_plate',
    legible: true,
    summary: 'Legible — Worcester Greenstar 24 kW combi',
    key_fields: { make: 'Worcester', model: 'Greenstar 24i', output_kw: '24', efficiency: '92%' },
    confidence: 'high',
    retake_hint: null,
    privacy_warning: null,
  },
  radiators: {
    kind: 'radiators',
    legible: true,
    summary: 'Legible — double panel radiator, ~1.2 m wide',
    key_fields: { type: 'double panel', width_m: '1.2', height_m: '0.6' },
    confidence: 'medium',
    retake_hint: null,
    privacy_warning: null,
  },
  fuse_cutout: {
    kind: 'fuse_cutout',
    legible: true,
    summary: 'Legible — 60 A main fuse, single-phase',
    key_fields: { rating_a: '60', phases: '1' },
    confidence: 'high',
    retake_hint: null,
    privacy_warning: null,
  },
  outdoor_space: {
    kind: 'outdoor_space',
    legible: true,
    summary: 'Clear space for wall-mounted unit beside rear door',
    key_fields: { mounting: 'wall', clearance_m: '≥1' },
    confidence: 'medium',
    retake_hint: null,
    privacy_warning: null,
  },
  gas_bill: {
    kind: 'gas_bill',
    legible: true,
    summary: 'Legible — 12 months usage, ~12,000 kWh/year',
    key_fields: { annual_kwh: '12000', supplier: 'Octopus Energy' },
    confidence: 'high',
    retake_hint: null,
    privacy_warning: null,
  },
}

export function mockPhotoCheck(kind: PhotoKind, blurry = false): PhotoCheckResult {
  const meta = { expected_kind: kind, model: 'gemini-3.8-flash', elapsed_ms: 3400 }
  if (blurry) {
    return {
      ...meta,
      kind,
      matches_expected: true,
      legible: false,
      usable: false,
      summary: "Couldn't read this — too blurry",
      key_fields: {},
      confidence: 'low',
      retake_hint: 'Move closer, avoid glare, fill the frame with the label or bill',
      privacy_warning: null,
    }
  }
  return { ...meta, ...PHOTO_MOCKS[kind], matches_expected: true, usable: true }
}

function entry(
  id: string,
  input: string,
  step: VerificationLogEntry['step'],
  model: string,
  check: string,
  passed: boolean,
  action: string,
  offsetMs: number,
): VerificationLogEntry {
  return { id, input, step, model, check, passed, action, at: new Date(Date.now() + offsetMs).toISOString() }
}

function mockLog(): VerificationLogEntry[] {
  return [
    entry('boiler_plate-v1', 'boiler_plate', 'read', 'gemini-3.8-flash', 'Gemini reads the input', true, '{"make": "Worcester", "model": "Greenstar 24i"}', 0),
    entry('boiler_plate-v2', 'boiler_plate', 'check', 'code', 'model found in datasheet library: matched', true, 'ok', 300),
    entry('boiler_plate-v3', 'boiler_plate', 'pass', 'code', 'all checks passed', true, 'use this reading', 350),
    entry('radiators-v1', 'radiators', 'read', 'gemini-3.8-flash', 'Gemini reads the input', true, '{"radiator_type": "other"}', 500),
    entry('radiators-v2', 'radiators', 'check', 'code', 'radiator legible: model reports it cannot read the radiator', false, 'ask Gemini to look again', 600),
    entry('radiators-v3', 'radiators', 'reread', 'gemini-4-argon', 'Gemini re-reads with the failed checks', true, '{"radiator_type": "K2", "height_mm": 600, "width_mm": 1200}', 900),
    entry('radiators-v4', 'radiators', 'pass', 'code', 'all checks passed', true, 'use this reading', 950),
    entry('gas_bill-v1', 'gas_bill', 'read', 'gemini-4-argon', 'Gemini reads the input', true, '{"total_kwh": 12000}', 1200),
    entry('gas_bill-v2', 'gas_bill', 'check', 'code', 'period covers about a year: 365 days', true, 'ok', 1250),
    entry('gas_bill-v3', 'gas_bill', 'pass', 'code', 'all checks passed', true, 'use this reading', 1300),
    entry('survey-v1', 'maths', 'check', 'code', 'Estimate A vs B: ratio 1.85 (fabric_higher)', false, 'explain the gap: 4 ranked reason(s)', 1500),
  ]
}

const READ_STATUS: Partial<Record<PhotoKind, InputReading['status']>> = {
  boiler_plate: 'verified',
  radiators: 'verified',
  fuse_cutout: 'verified',
  gas_bill: 'verified',
}

/** Offline plan: same numbers as backend `build_all_electric_plan` for Sam (60 A, 5-7 kW). */
export const SAM_PLAN: AllElectricPlan = {
  steps: [
    {
      id: 'supply',
      title: 'Electricity supply',
      order_reason:
        'Heat pumps and EV chargers both draw on the same main fuse; check headroom first.',
      status: 'flagged',
      headline:
        'A 60 A fuse is usually enough for a 7 kW heat pump (~15 A plus ~30 A household), but a 7.4 kW EV charger (~32 A) on the same fuse likely needs a supply upgrade. Ask your network operator before booking the charger. Your installer must notify the network operator of a heat pump install; this app does not contact them.',
      detail:
        'Heat pump ~15.2 A running (+15 A start allowance) · household ~30 A · EV charger 7.4 kW (~32.2 A)',
    },
    {
      id: 'heat_pump',
      title: 'Heat pump + grant',
      order_reason:
        'Size and flow temperature come from your house; the grant depends on your current fuel.',
      status: 'info',
      headline:
        'Target 5-7 kW at up to 45C flow, with a BUS grant of £7,500 (Boiler Upgrade Scheme grant when replacing a gas boiler (illustrative eligibility).).',
    },
    {
      id: 'solar',
      title: 'Solar',
      order_reason: 'Once heating is sized, generation offsets the higher electricity bill.',
      status: 'ok',
      headline:
        "About 3,584 kWh/year from a 3.5 kWp south-facing array at the N10 district centroid; simple payback about 5.2 years at today's electricity price (not a quote).",
    },
    {
      id: 'ev',
      title: 'EV charging',
      order_reason:
        'A home charger comes last, only if the supply still has room after the heat pump.',
      status: 'flagged',
      headline:
        'A 7.4 kW home charger (~32.2 A) on the same fuse as the heat pump likely needs a supply upgrade; ask your network operator before booking the charger.',
    },
  ],
  supply: {
    status: 'flagged',
    fuse_rating_a: 60,
    heat_pump_thermal_kw: 7,
    heat_pump_running_a: 15.2,
    heat_pump_peak_a: 30.2,
    ev_charger_kw: 7.4,
    ev_draw_a: 32.2,
    household_a: 30,
    headroom_a: 14.8,
    heat_pump_fits: true,
    ev_fits_with_heat_pump: false,
    message:
      'A 60 A fuse is usually enough for a 7 kW heat pump (~15 A plus ~30 A household), but a 7.4 kW EV charger (~32 A) on the same fuse likely needs a supply upgrade. Ask your network operator before booking the charger. Your installer must notify the network operator of a heat pump install; this app does not contact them.',
  },
  heat_pump: {
    size_kw_low: 5,
    size_kw_high: 7,
    max_flow_temp_c: 45,
    grant_gbp: 7500,
    grant_note: 'Boiler Upgrade Scheme grant when replacing a gas boiler (illustrative eligibility).',
    message:
      'Target 5-7 kW at up to 45C flow, with a BUS grant of £7,500 (Boiler Upgrade Scheme grant when replacing a gas boiler (illustrative eligibility).).',
  },
  solar: {
    status: 'ok',
    annual_yield_kwh: 3584.4,
    payback_years: 5.2,
    array_kwp: 3.5,
    message:
      "About 3,584 kWh/year from a 3.5 kWp south-facing array at the N10 district centroid; simple payback about 5.2 years at today's electricity price (not a quote).",
  },
  ev: {
    status: 'flagged',
    message:
      'A 7.4 kW home charger (~32.2 A) on the same fuse as the heat pump likely needs a supply upgrade; ask your network operator before booking the charger.',
  },
  defaults: [],
}

export const SAM_RADIATOR_VIDEO: RadiatorVideoResult = {
  status: 'verified_with_warnings',
  attempts: 2,
  model: 'gemini-4-argon',
  radiator_count: 3,
  radiators: [
    {
      first_seen: '0:03',
      last_seen: '0:08',
      room: 'Living room',
      status: 'verified',
      radiator_type: 'K2',
      panels: 2,
      fin_rows: 2,
      width_mm: 1200,
      height_mm: 600,
      confidence: 'medium',
      could_not_judge: [],
      warnings: [],
      photo_request: null,
      upsize_status: 'upsize',
      output_at_flow_temp_w: 1030,
      heat_loss_w: 1570,
      required_output_dt50_w: 3250,
      min_flow_temp_c: 52,
    },
    {
      first_seen: '0:14',
      last_seen: '0:18',
      room: 'Hallway',
      status: 'couldnt_tell',
      radiator_type: null,
      panels: null,
      fin_rows: null,
      width_mm: null,
      height_mm: null,
      confidence: 'low',
      could_not_judge: ['Too much motion blur at 0:14 to see convector fins or width'],
      warnings: ['radiator 2 (0:14) width missing or implausible: null'],
      photo_request: "couldn't tell: photograph the radiator seen at 0:14",
      upsize_status: 'couldnt_tell',
      output_at_flow_temp_w: null,
      heat_loss_w: null,
      required_output_dt50_w: null,
      min_flow_temp_c: null,
    },
    {
      first_seen: '0:23',
      last_seen: '0:29',
      room: 'Main bedroom',
      status: 'verified',
      radiator_type: 'K2',
      panels: 2,
      fin_rows: 2,
      width_mm: 1400,
      height_mm: 600,
      confidence: 'medium',
      could_not_judge: [],
      warnings: [],
      photo_request: null,
      upsize_status: 'marginal',
      output_at_flow_temp_w: 1200,
      heat_loss_w: 1570,
      required_output_dt50_w: 3250,
      min_flow_temp_c: 48,
    },
  ],
  photo_requests: ["couldn't tell: photograph the radiator seen at 0:14"],
  could_not_judge: ['Too much motion blur at 0:14 to see convector fins or width'],
  warnings: ["couldn't tell: photograph the radiator seen at 0:14"],
  log: [
    entry(
      'radiator_video-v1',
      'radiator_video',
      'read',
      'gemini-4-argon',
      'Gemini watches the radiator walkthrough video',
      true,
      '3 radiator(s) spotted',
      600,
    ),
    entry(
      'radiator_video-v2',
      'radiator_video',
      'check',
      'code',
      'radiator 2 (0:14) width missing or implausible: null',
      false,
      'ask Gemini to look again',
      700,
    ),
    entry(
      'radiator_video-v3',
      'radiator_video',
      'reread',
      'gemini-4-argon',
      'Gemini re-watches with the failed checks',
      true,
      '2 verified, 1 uncertain',
      950,
    ),
    entry(
      'radiator_video-v4',
      'radiator_video',
      'pass',
      'code',
      'verified 2 radiator(s); 1 need a photo',
      true,
      'use verified radiators and request photos for uncertain ones',
      1000,
    ),
  ],
}

export function mockRadiatorVideo(): RadiatorVideoResult {
  return SAM_RADIATOR_VIDEO
}

export function mockAnalysisResult(kinds: PhotoKind[], hasRadiatorVideo = false): AnalysisResult {
  const all: PhotoKind[] = ['boiler_plate', 'radiators', 'fuse_cutout', 'outdoor_space', 'gas_bill']
  return {
    survey_id: null,
    saved: false,
    storage_note: 'Offline demo data: nothing is saved.',
    postcode_district: 'N10',
    epc: {
      property_type: 'semi_detached',
      floor_area_m2: 90,
      age_band: '1930-1949',
      year_built: 1930,
      wall_type: 'cavity_unfilled',
      glazing: 'double_unknown_date',
      loft_insulation_mm: 100,
      floor_insulated: false,
      main_heating_fuel: 'gas',
      current_energy_efficiency_band: 'D',
      walls: ['cavity wall, as built, no insulation (assumed)'],
      roofs: ['pitched, 100 mm loft insulation'],
      floors: ['suspended, no insulation (assumed)'],
      windows: ['fully double glazed'],
      main_heating: ['boiler and radiators, mains gas'],
    },
    bundle: SAM_ANALYSIS,
    size_basis: 'measured',
    readings: all.map((kind) => {
      const active = kinds.includes(kind)
      const status = active ? (READ_STATUS[kind] ?? 'verified') : 'not_provided'
      const reading =
        kind === 'fuse_cutout' && active
          ? { rating_a: 60, legible: true, confidence: 'high', notes: '' }
          : null
      return {
        kind,
        status,
        attempts: kind === 'radiators' ? 2 : 1,
        reading,
        warnings: [],
        photograph_instead: null,
        used_for: '',
      }
    }),
    radiator_video: hasRadiatorVideo ? SAM_RADIATOR_VIDEO : null,
    gaps: hasRadiatorVideo
      ? [
          {
            input: 'radiator_video',
            message: "couldn't tell: photograph the radiator seen at 0:14",
            provide: "couldn't tell: photograph the radiator seen at 0:14",
          },
        ]
      : [],
    defaults: [
      {
        input: 'radiators',
        name: 'photographed_room_share_of_heat_loss',
        value: '20% of 4.7 kW',
        note: 'No room sizes from one photo: assumes the room is about a fifth of the house\'s heat loss.',
        confidence: 'low',
      },
    ],
    plan: SAM_PLAN,
    log: hasRadiatorVideo ? [...mockLog(), ...SAM_RADIATOR_VIDEO.log] : mockLog(),
    timings_ms: {},
  }
}

export function mockAnalysisEvents(kinds: PhotoKind[], hasRadiatorVideo = false): AnalysisEvent[] {
  const result = mockAnalysisResult(
    kinds.length ? kinds : ['boiler_plate', 'radiators', 'gas_bill'],
    hasRadiatorVideo,
  )
  return [
    { type: 'step', step: 'epc', status: 'running', ms: null },
    ...result.log.map((e): AnalysisEvent => ({ type: 'log', entry: e })),
    { type: 'step', step: 'epc', status: 'done', ms: 900 },
    { type: 'result', result },
  ]
}

function mockVerified(kw: number): VerifiedReading {
  return {
    kind: 'quote',
    status: 'verified',
    reading: { heat_pump_kw: kw },
    attempts: 1,
    warnings: [],
    photograph_instead: null,
    datasheet_id: null,
    log: [],
  }
}

export function mockReview(quoteIds: string[]): ReviewResult {
  return {
    review: {
      estimates_explanation:
        'Your bills point to about 4.7 kW; the fabric calc says 8.75 kW. The likeliest reason is cavity walls filled since the EPC, then the default air change rate.',
      cited_reason_codes: ['missed_insulation', 'default_air_change_rate'],
      quote_reviews: quoteIds.map((id) => ({
        quote_id: id,
        flags: [{ severity: 'amber', message: 'Ask how the size was chosen.', evidence: 'Target size 5-7 kW.' }],
      })),
      questions_to_ask: ['Can I see the room-by-room heat loss calculation?'],
      summary: 'A 5-7 kW unit at 45°C or below fits what your bills show.',
    },
    stripped: [
      { where: 'summary', text: 'This saves you £3,456 a year.', numbers: ['3,456'] },
    ],
    datasheets_used: [],
    model: 'gemini-4-argon',
    log: [],
    disclaimer:
      'A second opinion with confidence ranges, not financial advice. Nothing is sent to installers or network operators. It advises; you decide.',
  }
}

export const SAM_QUOTE_CHECKS: QuoteCheckResult[] = [
  {
    filename: 'installer-a-9kw.pdf',
    quoted_kw: 9,
    verified: mockVerified(9),
    design_flow_temp_c: 55,
    flags: [
      {
        severity: 'red',
        message: '9 kW quoted — your bills suggest about 5 kW (range 3.7–5.7 kW): likely oversized',
        evidence: 'Measured design load central 4.7 kW; target size 5–7 kW',
      },
      {
        severity: 'amber',
        message: 'Design flow 55 °C — expect higher running costs',
        evidence: 'At 55 °C annual saving is negative vs gas at price cap',
      },
      {
        severity: 'amber',
        message: 'Buffer tank specified — ask why (often unnecessary on modern combi replacements)',
        evidence: 'Quote line item: 50 L buffer vessel',
      },
    ],
    questions_to_ask: [
      'What heat loss calculation did you use, and can I see the room-by-room figures?',
      'Why 55 °C flow — can the system run at 45 °C with radiator changes only in the living room?',
      'Why is a buffer tank needed for this property?',
      'Is the £7,500 BUS grant deducted on the invoice?',
    ],
  },
  {
    filename: 'installer-b-12kw.pdf',
    quoted_kw: 12,
    verified: mockVerified(12),
    design_flow_temp_c: 50,
    flags: [
      {
        severity: 'red',
        message: '12 kW quoted — well above measured need; oversizing risks cycling and efficiency loss',
        evidence: 'Target range 5–7 kW; 12 kW exceeds high bound by ~70%',
      },
      {
        severity: 'amber',
        message: 'Grant not shown as deducted',
        evidence: 'No BUS line on quote summary',
      },
    ],
    questions_to_ask: [
      'Please justify 12 kW against a bill-based load of ~5 kW.',
      'Will the grant be applied before I pay the deposit?',
    ],
  },
  {
    filename: 'installer-c-6kw.pdf',
    quoted_kw: 6,
    verified: mockVerified(6),
    design_flow_temp_c: 40,
    flags: [
      {
        severity: 'info',
        message: '6 kW sits inside target range 5–7 kW',
        evidence: 'Target central 6 kW',
      },
      {
        severity: 'amber',
        message: 'Living room radiator may need upsizing for 45 °C design',
        evidence: 'Radiator check: upsize at 45 °C flow',
      },
    ],
    questions_to_ask: [
      'Is the living room radiator upgrade included in this price?',
      'What monitoring is included for the first year?',
    ],
  },
]
