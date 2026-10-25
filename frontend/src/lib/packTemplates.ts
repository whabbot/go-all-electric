import type {
  AnalysisResult,
  CrossCheck,
  Exact,
  InstallerDraftsRequest,
  PackQuoteReading,
  QuoteCheckResult,
  Range,
} from '../api/types'

export function formatRangeText(range: Range, unit = '', decimals = 1): string {
  const f = (n: number) => n.toFixed(decimals)
  return `${f(range.low)}–${f(range.central)}–${f(range.high)}${unit} (low–central–high)`
}

export function formatExactText(exact: Exact, unit = '', decimals = 0): string {
  return `${exact.value.toFixed(decimals)}${unit} (confidence: ${exact.confidence})`
}

function crossCheckVerdictText(check: CrossCheck): string {
  if (check.verdict === 'fabric_higher') return 'Fabric calc reads higher than your bills'
  if (check.verdict === 'measured_higher') return 'Your bills read higher than the fabric calc'
  return 'Estimates agree'
}

function houseContextBlock(analysis: AnalysisResult): string {
  const spec = analysis.bundle.target_spec
  const lines = [
    'For this home our numbers suggest:',
    `• Target heat pump size: ${formatRangeText(spec.size_kw, ' kW', 0)}`,
    `• Design flow temperature (max): ${formatExactText(spec.max_flow_temp_c, ' °C', 0)}`,
  ]
  const measured = analysis.bundle.measured
  if (measured) {
    lines.push(
      `• Measured design heat loss (from gas bill): ${formatRangeText(measured.design_load_kw, ' kW', 1)}`,
    )
  } else {
    lines.push('• Measured design heat loss: not available (no usable gas bill).')
  }
  return lines.join('\n')
}

export function buildInstallerQuestionDraft(quote: QuoteCheckResult, analysis: AnalysisResult): string {
  const lines: string[] = [
    'Questions for my installer (draft — please review before sending)',
    '',
    houseContextBlock(analysis),
    '',
    `About your quote (${quote.filename}):`,
  ]

  if (quote.quoted_kw != null) {
    lines.push(`• Quoted heat pump size: ${quote.quoted_kw} kW (from your quote document).`)
  }
  if (quote.design_flow_temp_c != null) {
    lines.push(`• Quoted design flow: ${quote.design_flow_temp_c} °C (from your quote document).`)
  }

  if (quote.flags.length > 0) {
    lines.push('', 'Our checker flagged:')
    for (const f of quote.flags) {
      lines.push(`• [${f.severity}] ${f.message}`)
      lines.push(`  Evidence: ${f.evidence}`)
    }
  }

  if (quote.questions_to_ask.length > 0) {
    lines.push('', 'Questions I would like answered:')
    for (const q of quote.questions_to_ask) {
      lines.push(`• ${q}`)
    }
  } else if (quote.flags.length === 0) {
    lines.push('', 'No specific questions were generated for this quote.')
  }

  lines.push('', 'Property: [your address]')
  return lines.join('\n')
}

export function buildHouseSummaryDraft(analysis: AnalysisResult): string {
  const { fabric, measured, cross_check: check, target_spec: spec } = analysis.bundle
  const lines: string[] = [
    'House summary for installers (draft — please review before sharing)',
    '',
    'Property: [your address]',
    '',
    'Heat loss estimates',
    `• Estimate A — fabric (EPC register + photos): ${fabric ? formatRangeText(fabric.design_load_kw, ' kW', 1) : "unavailable; see EPC gap and confirm at survey"} — source: government EPC data and radiator/boiler photos.`,
  ]

  if (measured) {
    lines.push(
      `• Estimate B — measured (gas bill): ${formatRangeText(measured.design_load_kw, ' kW', 1)} — source: photographed gas bill and degree-day maths.`,
      `  Heat transfer coefficient: ${formatRangeText(measured.htc_w_per_k, ' W/K', 1)}.`,
    )
  } else {
    lines.push('• Estimate B — measured: not available (no usable gas bill photographed).')
  }

  lines.push('')
  if (check) {
    lines.push('Cross-check')
    lines.push(`• Verdict: ${crossCheckVerdictText(check)}`)
    lines.push(
      `• Fabric ÷ measured ratio: ${formatRangeText(check.ratio, '×', 2)} — gap about ${check.gap_w_per_k.toFixed(0)} W/K.`,
    )
    const top = check.reasons.slice(0, 3)
    if (top.length > 0) {
      lines.push('• Top reasons they disagree:')
      for (const r of top) {
        lines.push(`  – ${r.explanation}`)
      }
    }
  } else {
    lines.push('Cross-check: not run (need a usable gas bill to compare A and B).')
  }

  lines.push(
    '',
    'Target installation',
    `• Heat pump size range: ${formatRangeText(spec.size_kw, ' kW', 0)} — ${
      analysis.size_basis === 'measured'
        ? 'sized from measured load where possible.'
        : 'sized from fabric only (no bill).'
    }`,
    `• Maximum flow temperature: ${formatExactText(spec.max_flow_temp_c, ' °C', 0)}`,
  )

  const upsize = spec.radiators.filter((r) => r.status === 'upsize')
  if (spec.radiators.length === 0) {
    lines.push('• Radiators: could not check — add a clear radiator photo.')
  } else if (upsize.length === 0) {
    lines.push('• Radiators to upsize: none flagged at design flow (from radiator photo).')
  } else {
    lines.push('• Radiators to upsize (from radiator photo):')
    for (const r of upsize) {
      lines.push(
        `  – ${r.room}: needs ~${Math.round(r.required_output_dt50_w)} W (ΔT50) or higher flow at ${r.flow_temp_c} °C`,
      )
    }
  }

  const fuse = analysis.plan?.supply.fuse_rating_a
  if (fuse != null) {
    lines.push(`• Main fuse (from fuse cutout photo): ${fuse} A`)
  } else {
    lines.push('• Main fuse: not available (no fuse cutout reading).')
  }

  lines.push(
    `• Grant: £${spec.grant.amount_gbp.value.toFixed(0)} (confidence: ${spec.grant.amount_gbp.confidence}) — ${spec.grant.note}`,
  )

  return lines.join('\n')
}

export function buildNetworkOperatorDraft(analysis: AnalysisResult): string {
  const plan = analysis.plan
  const spec = analysis.bundle.target_spec
  const lines: string[] = [
    'Draft note to network operator (not an application — please review before sending)',
    '',
    'Property: [your address]',
    '',
  ]

  if (!plan) {
    lines.push('Plan not available — run estimates first.')
    return lines.join('\n')
  }

  lines.push(
    'I am planning a heat pump installation. My installer will normally notify you of the heat pump; I am writing to ask about supply capacity before I commit.',
    '',
    `• Planned heat pump thermal size: ${formatRangeText(spec.size_kw, ' kW', 0)} (from our house survey).`,
  )

  const fuse = plan.supply.fuse_rating_a
  if (fuse != null) {
    lines.push(`• Main fuse rating (from fuse cutout photo): ${fuse} A`)
    lines.push(
      `• Estimated heat pump running draw: ~${plan.supply.heat_pump_running_a.toFixed(1)} A (peak allowance ~${plan.supply.heat_pump_peak_a.toFixed(1)} A) for up to ${plan.supply.heat_pump_thermal_kw} kW thermal.`,
    )
  } else {
    lines.push('• Main fuse rating: not available (no fuse cutout photo).')
  }

  const evKw = plan.supply.ev_charger_kw
  if (evKw > 0) {
    lines.push(
      `• I am also considering a ${evKw} kW home EV charger (~${plan.supply.ev_draw_a.toFixed(1)} A).`,
    )
    if (fuse != null) {
      lines.push(
        plan.supply.ev_fits_with_heat_pump
          ? '• Our check suggests this may fit on the existing fuse with the heat pump — please confirm.'
          : '• Our check suggests the charger may not fit on the same fuse as the heat pump — please advise on supply headroom or upgrade.',
      )
    }
  }

  lines.push(
    '',
    'Please advise whether my supply can support these loads and whether any upgrade or notification is needed. This is an enquiry only — not a formal application.',
    '',
    'I will send this myself; nothing is submitted from the Go All-Electric app.',
  )

  return lines.join('\n')
}

const READING_FIELDS: (keyof PackQuoteReading)[] = [
  'heat_pump_make',
  'heat_pump_model',
  'heat_pump_kw',
  'design_flow_temp_c',
  'buffer_tank',
  'total_gbp',
  'grant_deducted',
  'grant_amount_gbp',
  'mcs_heat_loss_kw',
]

/**
 * What the Gemini drafter sees: our numbers, the quote checker's flags and allowlisted quote
 * fields, by quote label. Never the address, file name, notes or line items.
 */
export function buildInstallerDraftsRequest(
  analysis: AnalysisResult,
  quotes: { label: string; result: QuoteCheckResult }[],
): InstallerDraftsRequest {
  const { measured, target_spec: spec } = analysis.bundle
  return {
    bundle: {
      size_kw: spec.size_kw,
      max_flow_temp_c: spec.max_flow_temp_c.value,
      measured_design_load_kw: measured?.design_load_kw ?? null,
      htc_w_per_k: measured?.htc_w_per_k ?? null,
      grant_gbp: spec.grant.amount_gbp.value,
    },
    quotes: quotes.map(({ label, result }) => {
      const read = result.verified.reading
      return {
        label,
        reading: read
          ? (Object.fromEntries(READING_FIELDS.map((k) => [k, read[k] ?? null])) as PackQuoteReading)
          : null,
        flags: result.flags.map(({ severity, message, evidence }) => ({ severity, message, evidence })),
        questions: result.questions_to_ask,
      }
    }),
    fuse_rating_a: analysis.plan?.supply.fuse_rating_a ?? null,
  }
}
