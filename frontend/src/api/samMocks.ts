import type {
  AnalysisBundle,
  CostComparison,
  EpcAddress,
  PhotoCheckResult,
  PhotoKind,
  QuoteCheckResult,
  VerificationLogEntry,
} from './types'

const r = (low: number, central: number, high: number) => ({ low, central, high })

export const SAM_EPC_ADDRESSES: EpcAddress[] = [
  {
    lmk_key: 'sam-demo-1',
    address: '14 Oakwood Avenue, London',
    postcode: 'N10 2AB',
    property_type: 'Semi-detached',
    floor_area_m2: 90,
    year_built: 1930,
  },
  {
    lmk_key: 'sam-demo-2',
    address: '16 Oakwood Avenue, London',
    postcode: 'N10 2AB',
    property_type: 'Semi-detached',
    floor_area_m2: 88,
    year_built: 1932,
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

const PHOTO_MOCKS: Record<PhotoKind, PhotoCheckResult> = {
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
    summary: 'Legible — 100 A main fuse, single-phase',
    key_fields: { rating_a: '100', phases: '1' },
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
  if (blurry) {
    return {
      kind,
      legible: false,
      summary: "Couldn't read this — too blurry",
      key_fields: {},
      confidence: 'low',
      retake_hint: 'Move closer, avoid glare, fill the frame with the label or bill',
      privacy_warning: null,
    }
  }
  return { ...PHOTO_MOCKS[kind] }
}

export function mockVerificationStream(): VerificationLogEntry[] {
  const base = Date.now()
  return [
    {
      id: '1',
      step: 'read',
      model: 'gemini-4-argon',
      check: 'Boiler data plate OCR',
      passed: true,
      action: 'Read make, model, kW rating, efficiency',
      at: new Date(base).toISOString(),
    },
    {
      id: '2',
      step: 'check',
      model: 'gemini-4-argon',
      check: 'Privacy scan',
      passed: true,
      action: 'No faces or number plates stored',
      at: new Date(base + 400).toISOString(),
    },
    {
      id: '3',
      step: 'read',
      model: 'gemini-4-argon',
      check: 'Gas bill annual kWh',
      passed: true,
      action: 'Extracted 12-month total',
      at: new Date(base + 900).toISOString(),
    },
    {
      id: '4',
      step: 'reread',
      model: 'gemini-4-argon',
      check: 'Bill period cross-check',
      passed: true,
      action: 'Monthly sum matches annual total',
      at: new Date(base + 1400).toISOString(),
    },
    {
      id: '5',
      step: 'pass',
      model: 'gae-heatpump',
      check: 'Measured vs fabric cross-check',
      passed: true,
      action: 'Estimates disagree — reasons ranked',
      at: new Date(base + 2000).toISOString(),
    },
  ]
}

export const SAM_QUOTE_CHECKS: QuoteCheckResult[] = [
  {
    filename: 'installer-a-9kw.pdf',
    quoted_kw: 9,
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
