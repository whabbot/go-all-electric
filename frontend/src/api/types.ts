/** Mirrors the backend: heatpump maths core, Gemini readings and the survey analysis call. */

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

export type DetectedKind = PhotoKind | 'gas_meter' | 'consumer_unit' | 'other'

export type PhotoCheckResult = {
  kind: DetectedKind
  expected_kind: PhotoKind
  matches_expected: boolean
  legible: boolean
  usable: boolean
  summary: string
  key_fields: Record<string, string>
  confidence: Confidence
  retake_hint: string | null
  privacy_warning: string | null
  model: string
  elapsed_ms: number
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
  /** Which input the entry is about, e.g. `gas_bill`, `radiators`, `review`. */
  input: string
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

export type QuoteUploadGroup = {
  quoteName: string
  pages: File[]
}

export type ReadingStatus = 'verified' | 'verified_with_warnings' | 'couldnt_tell'

export type RadiatorKind =
  | 'single_panel'
  | 'K1'
  | 'P+'
  | 'K2'
  | 'K3'
  | 'column'
  | 'towel_rail'
  | 'other'

export type UpsizeStatus = 'ok' | 'marginal' | 'upsize' | 'couldnt_tell'

export type VerifiedVideoRadiator = {
  first_seen: string
  last_seen: string | null
  room: string | null
  status: ReadingStatus
  radiator_type: RadiatorKind | null
  panels: number | null
  fin_rows: number | null
  width_mm: number | null
  height_mm: number | null
  confidence: Confidence
  could_not_judge: string[]
  warnings: string[]
  photo_request: string | null
  upsize_status: UpsizeStatus
  output_at_flow_temp_w: number | null
  heat_loss_w: number | null
  required_output_dt50_w: number | null
  min_flow_temp_c: number | null
}

export type RadiatorVideoResult = {
  status: ReadingStatus
  attempts: number
  model: string
  radiator_count: number
  radiators: VerifiedVideoRadiator[]
  photo_requests: string[]
  could_not_judge: string[]
  warnings: string[]
  log: VerificationLogEntry[]
}

export type VerifiedReading = {
  kind: string
  status: ReadingStatus
  reading: Record<string, unknown> | null
  attempts: number
  warnings: string[]
  photograph_instead: string | null
  datasheet_id: string | null
  log: VerificationLogEntry[]
}

export type QuoteCheckResult = {
  filename: string
  quoted_kw: number | null
  design_flow_temp_c: number | null
  flags: QuoteFlag[]
  questions_to_ask: string[]
  verified: VerifiedReading
}

/** From the analysis bundle, so quote flags compare against this home's numbers. */
export type QuoteSizeContext = {
  size_low_kw: number
  size_high_kw: number
  design_load_kw: number | null
}

/** One EPC search row. The address is for picking only: after that the UI shows the district. */
export type EpcAddress = {
  certificate_id: string
  address: string
  postcode: string
  registration_date: string
  current_energy_efficiency_band: string | null
}

/** `measured` and `cross_check` are null when there is no usable gas bill (no Estimate B). */
export type AnalysisBundle = {
  measured: MeasuredEstimate | null
  fabric: FabricEstimate
  cross_check: CrossCheck | null
  costs_by_flow_temp: CostComparison[]
  target_spec: TargetSpec
}

export type EpcSummary = {
  property_type: string
  floor_area_m2: number | null
  age_band: string | null
  year_built: number
  wall_type: string
  glazing: string
  loft_insulation_mm: number
  floor_insulated: boolean
  main_heating_fuel: string
  current_energy_efficiency_band: string | null
  walls: string[]
  roofs: string[]
  floors: string[]
  windows: string[]
  main_heating: string[]
}

export type InputReading = {
  kind: PhotoKind
  status: ReadingStatus | 'not_provided'
  attempts: number
  reading: Record<string, unknown> | null
  warnings: string[]
  photograph_instead: string | null
  used_for: string
}

export type NamedDefault = {
  input: string
  name: string
  value: string
  note: string
  confidence: Confidence
}

/** Something we couldn't tell, what it means, and what to provide instead. */
export type Gap = {
  input: string
  message: string
  provide: string
}

export type PlanStepStatus = 'ok' | 'flagged' | 'couldnt_tell' | 'info'

export type PlanSupply = {
  status: 'ok' | 'flagged' | 'couldnt_tell'
  fuse_rating_a: number | null
  heat_pump_thermal_kw: number
  heat_pump_running_a: number
  heat_pump_peak_a: number
  ev_charger_kw: number
  ev_draw_a: number
  household_a: number
  headroom_a: number | null
  heat_pump_fits: boolean
  ev_fits_with_heat_pump: boolean
  message: string
}

export type PlanHeatPump = {
  size_kw_low: number
  size_kw_high: number
  max_flow_temp_c: number
  grant_gbp: number
  grant_note: string
  message: string
}

export type PlanSolar = {
  status: 'ok' | 'couldnt_fetch'
  annual_yield_kwh: number | null
  payback_years: number | null
  array_kwp: number
  message: string
}

export type PlanEv = {
  status: PlanStepStatus
  message: string
}

export type PlanStep = {
  id: 'supply' | 'heat_pump' | 'solar' | 'ev'
  title: string
  order_reason: string
  status: PlanStepStatus
  headline: string
  detail?: string | null
}

export type AllElectricPlan = {
  steps: PlanStep[]
  supply: PlanSupply
  heat_pump: PlanHeatPump
  solar: PlanSolar
  ev: PlanEv
  defaults: NamedDefault[]
}

export type AnalysisResult = {
  survey_id: string | null
  saved: boolean
  storage_note: string | null
  postcode_district: string | null
  epc: EpcSummary
  bundle: AnalysisBundle
  size_basis: 'measured' | 'fabric'
  readings: InputReading[]
  radiator_video?: RadiatorVideoResult | null
  gaps: Gap[]
  defaults: NamedDefault[]
  plan: AllElectricPlan
  log: VerificationLogEntry[]
  timings_ms: Record<string, number>
}

export type AnalysisStepStatus = 'running' | 'done'

/** `POST /api/analysis` streams these as newline-delimited JSON. */
export type AnalysisEvent =
  | { type: 'step'; step: string; status: AnalysisStepStatus; ms: number | null }
  | { type: 'log'; entry: VerificationLogEntry }
  | { type: 'result'; result: AnalysisResult }
  | { type: 'error'; status: number; message: string }

export type ReviewFlag = {
  severity: QuoteFlagSeverity
  message: string
  evidence: string
}

export type ArgonReview = {
  estimates_explanation: string
  cited_reason_codes: ReasonCode[]
  quote_reviews: { quote_id: string; flags: ReviewFlag[] }[]
  questions_to_ask: string[]
  summary: string
}

/** A sentence removed because a number in it doesn't trace back to our maths or your documents. */
export type StrippedClaim = {
  where: string
  text: string
  numbers: string[]
}

export type ReviewResult = {
  review: ArgonReview
  stripped: StrippedClaim[]
  datasheets_used: string[]
  model: string
  log: VerificationLogEntry[]
  disclaimer: string
}

export type ReviewQuote = {
  quote_id: string
  pages: File[]
  reading: Record<string, unknown> | null
}
