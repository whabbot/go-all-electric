import { useEffect, useState } from 'react'
import { useSession } from '../context/SessionContext'
import { VerificationLogPanel } from './VerificationLog'

/** Gemini 4 Argon at high thinking takes 1.5-2 minutes for the whole context. */
const EXPECTED_MS = 105_000

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
  const { analysis, review, startReview, quotes } = useSession()
  if (!analysis) return null
  const checked = quotes.filter((q) => q.result).length

  return (
    <section className="card review-panel">
      <h2>One-context review</h2>
      <p className="subtle">
        Gemini 4 Argon reads every photo, the bill, the EPC building fields, matched datasheets,{' '}
        {checked > 0 ? `${checked} quote${checked === 1 ? '' : 's'}` : 'any checked quotes'} and our maths together,
        and explains them. It never sees your address. It doesn&apos;t calculate: any sentence with a number we
        can&apos;t trace is removed and listed below.
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
