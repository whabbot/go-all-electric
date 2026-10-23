/** Mirrors backend heatpump maths-core and planned Gemini / quote-check payloads. */

export type Confidence = 'low' | 'medium' | 'high'

export type Range = {
  low: number
  central: number
  high: number
}

export type Exact = {
  value: number
  confidence: Confidence
}

export type MeasuredCaveat =
  | 'baseline_estimated'
  | 'efficiency_defaulted'
  | 'possibly_sunny'
  | 'possibly_partially_heated'

export type MeasuredEstimate = {
  heating_gas_kwh: Range
  baseline_gas_kwh: Range
  boiler_efficiency: number
  htc_w_per_k: Range
  design_load_kw: Range
  indoor_temp_c: number
  design_outdoor_temp_c: number
  caveats: MeasuredCaveat[]
}

export type FabricDefault =
  | 'installer_air_change_rate'
  | 'double_glazing_u_2_8'
  | 'wall_u_as_built'
  | 'roof_u_from_loft_depth'
  | 'floor_u'
  | 'geometry_from_floor_area'

export type FabricAssumption = {
  default: FabricDefault
  value: number
  unit: string
  note: string
}

export type FabricEstimate = {
  element_w_per_k: Record<string, number>
  htc_w_per_k: Range
  design_load_kw: Range
  assumptions: FabricAssumption[]
  wall_type: string
  glazing: string
  loft_insulation_mm: number
  net_wall_area_m2: number
  window_area_m2: number
  roof_area_m2: number
  volume_m3: number
  air_change_rate: number
  built_before_2000: boolean
}

export type CrossCheckVerdict = 'agree' | 'fabric_higher' | 'measured_higher'

export type ReasonCode =
  | 'default_air_change_rate'
  | 'default_glazing_u'
  | 'missed_insulation'
  | 'sunny_or_part_heated'
  | 'boiler_efficiency_overstated'
  | 'home_kept_warmer'
  | 'draughtier_than_assumed'
  | 'insulation_overstated'

export type CrossCheckReason = {
  code: ReasonCode
  explanation: string
  drivers: string[]
  potential_w_per_k: number
  share_of_gap: number
}

export type CrossCheck = {
  verdict: CrossCheckVerdict
  ratio: Range
  gap_w_per_k: number
  reasons: CrossCheckReason[]
}

export type Prices = {
  electricity_pence_per_kwh: number
  gas_pence_per_kwh: number
  period: string
}

export type CostComparison = {
  design_flow_temp_c: number
  space_heat_kwh: number
  hot_water_heat_kwh: number
  space_heating_scop: Range
  gas_cost_gbp: Exact
  heat_pump_cost_gbp: Range
  annual_saving_gbp: Range
  break_even_scop: Exact
  break_even_flow_temp_c: Range
  prices: Prices
}

export type RadiatorStatus = 'ok' | 'marginal' | 'upsize'

export type RadiatorCheck = {
  room: string
  flow_temp_c: number
  output_w: number
  heat_loss_w: number
  status: RadiatorStatus
  required_output_dt50_w: number
  min_flow_temp_c: number
}

export type Grant = {
  amount_gbp: Exact
  fuel: string
  note: string
}

export type TargetSpec = {
  size_kw: Range
  max_flow_temp_c: Exact
  flow_temp_needed_by_current_radiators_c: Exact | null
  radiators: RadiatorCheck[]
  grant: Grant
}

export type PhotoKind =
  | 'boiler_plate'
  | 'radiators'
  | 'fuse_cutout'
  | 'outdoor_space'
  | 'gas_bill'

export type PhotoCheckResult = {
  kind: PhotoKind
  legible: boolean
  summary: string
  key_fields: Record<string, string>
  confidence: Confidence
  retake_hint: string | null
  privacy_warning: string | null
}

export type VerificationStep =
  | 'read'
  | 'check'
  | 'reread'
  | 'pass'
  | 'fail'

export type VerificationLogEntry = {
  id: string
  step: VerificationStep
  model: string
  check: string
  passed: boolean
  action: string
  at: string
}

export type QuoteFlagSeverity = 'info' | 'amber' | 'red'

export type QuoteFlag = {
  severity: QuoteFlagSeverity
  message: string
  evidence: string
}

export type QuoteCheckResult = {
  filename: string
  quoted_kw: number | null
  design_flow_temp_c: number | null
  flags: QuoteFlag[]
  questions_to_ask: string[]
}

export type EpcAddress = {
  lmk_key: string
  address: string
  postcode: string
  property_type: string
  floor_area_m2: number
  year_built: number
}

export type AnalysisBundle = {
  measured: MeasuredEstimate
  fabric: FabricEstimate
  cross_check: CrossCheck
  costs_by_flow_temp: CostComparison[]
  target_spec: TargetSpec
}
