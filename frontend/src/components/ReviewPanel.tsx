import { useEffect, useState } from 'react'
import type { ConflictField, EvidenceSource, TestedConflict } from '../api'
import { useSession } from '../context/SessionContext'
import { VerificationLogPanel } from './VerificationLog'

/** Gemini 4 Argon at high thinking takes 1.5-2 minutes for the whole context. */
const EXPECTED_MS = 105_000

const FIELD_LABEL: Record<ConflictField, string> = {
  wall_type: 'Wall insulation',
  loft_insulation_mm: 'Loft insulation depth',
  glazing: 'Window glazing',
  floor_insulated: 'Floor insulation',
  air_changes_per_hour: 'Air change rate',
  heating_system: 'Heating system',
}

const EVIDENCE_LABEL: Record<EvidenceSource, string> = {
  boiler_plate: 'Boiler data plate photo',
  gas_bill: 'Gas bill',
  radiators: 'Radiator photo',
  radiator_video: 'Radiator walkthrough video',
  fuse_cutout: 'Fuse cutout photo',
  outdoor_space: 'Outdoor unit spot photo',
  epc: 'EPC record',
  quotes: 'Installer quotes',
}

const VALUE_LABEL: Record<string, string> = {
  solid_brick: 'uninsulated solid brick',
  solid_insulated: 'insulated solid walls',
  cavity_unfilled: 'unfilled cavity walls',
  cavity_filled: 'filled cavity walls',
  timber_frame: 'timber frame',
  loft_0mm: 'no loft insulation (0 mm)',
  '0': 'no loft insulation (0 mm)',
  loft_100mm: '100 mm loft insulation',
  '100': '100 mm loft insulation',
  loft_200mm: '200 mm loft insulation',
  '200': '200 mm loft insulation',
  loft_270mm: '270 mm+ loft insulation',
  '270': '270 mm+ loft insulation',
  single: 'single glazing',
  double_old: 'older double glazing',
  double_unknown_date: 'older double glazing',
  double_post_2002: 'post-2002 double glazing',
  triple: 'triple glazing',
  floor_insulated_true: 'insulated floor',
  True: 'insulated floor',
  true: 'insulated floor',
  floor_insulated_false: 'uninsulated floor',
  False: 'uninsulated floor',
  false: 'uninsulated floor',
  ach_0_5: '0.5 air changes/hr (draught-proofed)',
  '0.5': '0.5 air changes/hr (draught-proofed)',
  ach_1_0: '1.0 air changes/hr (moderate)',
  '1.0': '1.0 air changes/hr (moderate)',
  '1': '1.0 air changes/hr (moderate)',
  ach_1_5: '1.5 air changes/hr (draughty default)',
  '1.5': '1.5 air changes/hr (draughty default)',
  condensing_boiler: 'condensing boiler',
  non_condensing_boiler: 'older non-condensing boiler',
}

function formatConflictValue(field: ConflictField, value: string): string {
  if (VALUE_LABEL[value]) return VALUE_LABEL[value]
  if (field === 'loft_insulation_mm' && /^\d+$/.test(value)) return `${value} mm loft insulation`
  return value.replaceAll('_', ' ')
}

function formatGapChange(c: TestedConflict): string {
  const verb =
    c.gap_change === 'shrinks'
      ? 'A-vs-B gap shrinks'
      : c.gap_change === 'grows'
        ? 'A-vs-B gap grows'
        : 'A-vs-B gap unchanged'
  if (c.original_gap_kw != null && c.revised_gap_kw != null) {
    return `${verb} (${c.original_gap_kw.toFixed(1)} → ${c.revised_gap_kw.toFixed(1)} kW)`
  }
  return verb
}

function ElapsedBar({ startedAt }: { startedAt: number }) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [])
  const elapsed = Math.max(0, now - startedAt)
  const seconds = Math.round(elapsed / 1000)
  // Never reaches 100% on time alone: the bar only fills when the answer arrives.
  const pct = Math.min(95, (elapsed / EXPECTED_MS) * 100)
  const stage =
    elapsed < 5_000
      ? 'Attaching photos, bill, EPC, datasheets, quotes and the maths…'
      : elapsed < EXPECTED_MS
        ? 'Gemini 4 Argon is reviewing everything in one context…'
        : 'Taking longer than usual; still waiting for Gemini 4 Argon…'
  return (
    <div role="status" aria-live="polite">
      <div className="progress-bar" aria-hidden="true">
        <span style={{ width: `${pct}%` }} />
      </div>
      <p className="subtle">
        {stage} {seconds}s (usually 90–120s). Then every number it writes is checked against our maths.
      </p>
    </div>
  )
}

export function ReviewPanel() {
  const { analysis, review, startReview, quotes, conflictDecisions, setConflictDecision } = useSession()
  if (!analysis) return null
  const checked = quotes.filter((q) => q.result).length
  const testedConflicts = review.status === 'done' ? (review.result.tested_conflicts ?? []) : []

  return (
    <section className="card review-panel">
      <h2>One-context review</h2>
      <p className="subtle">
        Gemini 4 Argon reads every photo, the bill, the EPC building fields, matched datasheets,{' '}
        {checked > 0 ? `${checked} quote${checked === 1 ? '' : 's'}` : 'any checked quotes'} and our maths together,
        and proposes which EPC input might be wrong so code can test it. It never sees your address. It doesn&apos;t
        calculate: any sentence with a number we can&apos;t trace is removed and listed below.
      </p>

      {review.status === 'idle' && (
        <button type="button" className="btn primary" onClick={startReview}>
          Ask Gemini to review everything
        </button>
      )}
      {review.status === 'running' && <ElapsedBar startedAt={review.startedAt} />}
      {review.status === 'failed' && (
        <>
          <p className="error">{review.message}</p>
          <button type="button" className="btn" onClick={startReview}>
            Try again
          </button>
        </>
      )}
      {review.status === 'done' && (
        <div className="review-result">
          <p className="subtle">
            {review.result.model}, {Math.round(review.elapsedMs / 1000)}s
          </p>
          <h3>Why the estimates differ</h3>
          <p>{review.result.review.estimates_explanation}</p>
          {testedConflicts.length > 0 && (
            <div className="conflict-section">
              <h3>What if the EPC is wrong here?</h3>
              <p className="subtle">
                Gemini proposed these EPC conflicts from your evidence; code re-ran Estimate A on each one. Headline
                estimates stay unchanged.
              </p>
              <ul className="conflict-list">
                {testedConflicts.map((c) => {
                  const key = `${c.field}:${c.proposed_value}`
                  const decision = conflictDecisions[key] ?? null
                  return (
                    <li
                      key={key}
                      className={`conflict-card${decision ? ` conflict-${decision}` : ''}`}
                    >
                      <div className="conflict-head">
                        <strong>
                          {FIELD_LABEL[c.field]}: {formatConflictValue(c.field, c.current_value)} →{' '}
                          {formatConflictValue(c.field, c.proposed_value)}
                        </strong>
                        <span className="conflict-source">
                          Evidence: {EVIDENCE_LABEL[c.evidence_source]}
                        </span>
                      </div>
                      <p className="conflict-summary">{c.evidence_summary}</p>
                      <p className="conflict-rerun">
                        <span>
                          Code re-run of Estimate A:{' '}
                          <strong>
                            {c.original_design_load_kw.central.toFixed(1)} kW →{' '}
                            {c.revised_design_load_kw.central.toFixed(1)} kW
                          </strong>{' '}
                          ({c.revised_design_load_kw.low.toFixed(1)}–
                          {c.revised_design_load_kw.high.toFixed(1)} kW)
                        </span>{' '}
                        <span className={`conflict-gap conflict-gap-${c.gap_change}`}>
                          {formatGapChange(c)}
                        </span>
                      </p>
                      <div className="conflict-actions">
                        <button
                          type="button"
                          className={`btn conflict-btn${decision === 'confirmed' ? ' primary' : ''}`}
                          aria-pressed={decision === 'confirmed'}
                          onClick={() =>
                            setConflictDecision(key, decision === 'confirmed' ? null : 'confirmed')
                          }
                        >
                          {decision === 'confirmed' ? 'Confirmed' : 'Confirm'}
                        </button>
                        <button
                          type="button"
                          className={`btn conflict-btn${decision === 'dismissed' ? ' active' : ''}`}
                          aria-pressed={decision === 'dismissed'}
                          onClick={() =>
                            setConflictDecision(key, decision === 'dismissed' ? null : 'dismissed')
                          }
                        >
                          {decision === 'dismissed' ? 'Dismissed' : 'Dismiss'}
                        </button>
                        {decision && (
                          <span className="subtle conflict-decision-note">
                            {decision === 'confirmed'
                              ? 'Confirmed for this session only.'
                              : 'Dismissed for this session only.'}
                          </span>
                        )}
                      </div>
                    </li>
                  )
                })}
              </ul>
            </div>
          )}
          {testedConflicts.length === 0 &&
            review.result.review.conflict_status === 'no_conflict_found' && (
              <p className="subtle">No EPC input conflicts found across your photos and readings.</p>
            )}
          {review.result.review.summary && (
            <>
              <h3>Summary</h3>
              <p>{review.result.review.summary}</p>
            </>
          )}
          {review.result.review.quote_reviews.map((qr) => (
            <div key={qr.quote_id}>
              <h3>{qr.quote_id}</h3>
              <ul className="flags">
                {qr.flags.map((f, i) => (
                  <li key={i} className={`flag flag-${f.severity}`}>
                    <strong>{f.message}</strong>
                    {f.evidence && <span className="evidence">{f.evidence}</span>}
                  </li>
                ))}
              </ul>
            </div>
          ))}
          {review.result.review.questions_to_ask.length > 0 && (
            <>
              <h3>Questions to ask</h3>
              <ul>
                {review.result.review.questions_to_ask.map((q) => (
                  <li key={q}>{q}</li>
                ))}
              </ul>
            </>
          )}
          <h3>Removed statements ({review.result.stripped.length})</h3>
          {review.result.stripped.length === 0 ? (
            <p className="subtle">None: every number traced back to our maths or your documents.</p>
          ) : (
            <>
              <p className="subtle">These had numbers we couldn&apos;t trace, so they are not shown above.</p>
              <ul className="stripped-list">
                {review.result.stripped.map((s, i) => (
                  <li key={i}>
                    {s.text} <span className="subtle">(untraced: {s.numbers.join(', ')})</span>
                  </li>
                ))}
              </ul>
            </>
          )}
          <VerificationLogPanel title="Review log" entries={review.result.log} />
          <p className="subtle">{review.result.disclaimer}</p>
          {review.quoteCount !== checked && (
            <button type="button" className="btn" onClick={startReview}>
              Review again with {checked} checked quote{checked === 1 ? '' : 's'}
            </button>
          )}
        </div>
      )}
    </section>
  )
}
