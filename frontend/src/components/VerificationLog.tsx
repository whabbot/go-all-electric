import type { VerificationLogEntry } from '../api'

const STEP_LABEL: Record<VerificationLogEntry['step'], string> = {
  read: 'read',
  check: 'check',
  reread: 're-read',
  pass: 'pass',
  fail: 'fail',
}

/** Keep each input's read -> check -> re-read -> outcome together, inputs in first-seen order. */
function groupByInput(entries: VerificationLogEntry[]): VerificationLogEntry[] {
  const order = new Map<string, number>()
  entries.forEach((e) => {
    if (!order.has(e.input)) order.set(e.input, order.size)
  })
  return entries
    .map((e, i) => ({ e, i }))
    .sort((a, b) => (order.get(a.e.input) ?? 0) - (order.get(b.e.input) ?? 0) || a.i - b.i)
    .map(({ e }) => e)
}

/** The real verification loop, entry by entry: what was read, what code checked, what happened. */
export function VerificationLogPanel({
  entries: raw,
  title = 'Verification log',
  live = false,
}: {
  entries: VerificationLogEntry[]
  title?: string
  /** Live logs keep arrival order; finished logs are grouped by input. */
  live?: boolean
}) {
  if (raw.length === 0) return null
  const entries = live ? raw : groupByInput(raw)
  const failed = entries.filter((e) => !e.passed).length
  const rereads = entries.filter((e) => e.step === 'reread').length

  return (
    <aside className="verification-log" aria-live={live ? 'polite' : 'off'}>
      <div className="log-head">
        <h3>{title}</h3>
        <p className="log-counts">
          {entries.length} steps ·{' '}
          <span className={failed > 0 ? 'log-fail-count' : 'log-ok-count'}>
            {failed} failed check{failed === 1 ? '' : 's'}
          </span>{' '}
          · {rereads} re-read{rereads === 1 ? '' : 's'}
        </p>
      </div>
      <ol>
        {entries.map((e) => (
          <li key={e.id} className={`log-row ${e.passed ? 'log-pass' : 'log-fail'} log-step-${e.step}`}>
            <span className="log-step">{STEP_LABEL[e.step]}</span>
            <span className="log-input">{e.input.replaceAll('_', ' ')}</span>
            <span className="log-model">{e.model}</span>
            <span className="log-check">
              <span className="log-mark" aria-label={e.passed ? 'passed' : 'failed'}>
                {e.passed ? '✓' : '✗'}
              </span>{' '}
              {e.check}
            </span>
            <span className="log-action">→ {e.action}</span>
          </li>
        ))}
      </ol>
    </aside>
  )
}
