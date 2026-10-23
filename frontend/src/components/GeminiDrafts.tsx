import { useEffect, useState } from 'react'
import type { InstallerDraft, InstallerDraftsResult } from '../api'
import { VerificationLogPanel } from './VerificationLog'

/** Gemini 4 Argon at medium thinking, one email per quote in parallel: usually under 10s. */
const EXPECTED_MS = 10_000

export type DraftingState =
  | { status: 'idle' }
  | { status: 'running'; startedAt: number }
  | { status: 'done'; result: InstallerDraftsResult; startedAt: number; elapsedMs: number }
  | { status: 'failed'; message: string }

function Progress({ startedAt }: { startedAt: number }) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 500)
    return () => clearInterval(t)
  }, [])
  const elapsed = Math.max(0, now - startedAt)
  // Never reaches 100% on time alone: the bar only fills when the drafts arrive.
  const pct = Math.min(95, (elapsed / EXPECTED_MS) * 100)
  return (
    <div role="status" aria-live="polite">
      <div className="progress-bar" aria-hidden="true">
        <span style={{ width: `${pct}%` }} />
      </div>
      <p className="subtle">
        {elapsed < EXPECTED_MS
          ? 'Gemini 4 Argon is drafting one email per quote…'
          : 'Taking longer than usual; still waiting for Gemini 4 Argon…'}{' '}
        {Math.round(elapsed / 1000)}s. Then every number is checked against our figures.
      </p>
    </div>
  )
}

type PanelProps = {
  quoteCount: number
  state: DraftingState
  onDraft: () => void
}

/** The one "Draft with Gemini" control for every installer email, with its progress and log. */
export function GeminiDraftsPanel({ quoteCount, state, onDraft }: PanelProps) {
  const done = state.status === 'done' ? state : null
  const argon = done?.result.drafts.filter((d) => d.source === 'argon').length ?? 0
  return (
    <section className="card pack-gemini">
      <h2>Draft the installer emails with Gemini</h2>
      <p className="subtle">
        Gemini 4 Argon writes one polite, technical email per quote from your measured figures and the
        quote check, asking for a re-quote on right-sized heat pumps from our datasheet library. Code
        then checks every number: a sentence with a number we can&apos;t trace is removed. If too much is
        removed, you get the template below instead. It sees numbers and quote labels only, never your
        address, photos or file names.
      </p>
      {state.status === 'idle' && (
        <button type="button" className="btn primary" onClick={onDraft}>
          Draft {quoteCount === 1 ? 'the email' : `all ${quoteCount} emails`} with Gemini
        </button>
      )}
      {state.status === 'running' && <Progress startedAt={state.startedAt} />}
      {state.status === 'failed' && (
        <>
          <p className="error">{state.message} The template drafts below still work.</p>
          <button type="button" className="btn" onClick={onDraft}>
            Try again
          </button>
        </>
      )}
      {done && (
        <>
          <p className="subtle">
            {argon} of {done.result.drafts.length} drafted by {done.result.model} in{' '}
            {Math.round(done.elapsedMs / 1000)}s
            {argon < done.result.drafts.length ? '; the rest use the template' : ''}. Review each one below
            before you copy it.
          </p>
          <VerificationLogPanel title="Drafting log" entries={done.result.drafts.flatMap((d) => d.log)} />
          <button type="button" className="btn" onClick={onDraft}>
            Draft again
          </button>
        </>
      )}
    </section>
  )
}

type ProvenanceProps = {
  draft: InstallerDraft
  showingGemini: boolean
  onToggle: () => void
}

/** Where one installer draft came from: model, library entries named, sentences removed. */
export function DraftProvenance({ draft, showingGemini, onToggle }: ProvenanceProps) {
  const isArgon = draft.source === 'argon'
  return (
    <div className="pack-provenance">
      {isArgon ? (
        <p className="privacy-ok">
          {showingGemini ? 'Drafted by Gemini 4 Argon; every number checked in code.' : 'Showing the template.'}{' '}
          <button type="button" className="link-btn" onClick={onToggle}>
            {showingGemini ? 'Use the template instead' : 'Use the Gemini draft'}
          </button>
        </p>
      ) : (
        <p className="warning">Template used: {draft.fallback_reason ?? 'the Gemini draft did not pass the checks'}.</p>
      )}
      {draft.models.length > 0 && (
        <>
          <p className="pack-draft-label">Re-quote asked on (from our datasheet library)</p>
          <ul className="pack-models">
            {draft.models.map((m) => (
              <li key={m.datasheet_id}>
                {m.make} {m.model}, {m.nominal_capacity_kw} kW{' '}
                <a href={m.source_url} target="_blank" rel="noreferrer">
                  datasheet
                </a>
              </li>
            ))}
          </ul>
        </>
      )}
      {draft.stripped.length > 0 && (
        <>
          <p className="pack-draft-label">Removed: number not traceable ({draft.stripped.length})</p>
          <ul className="stripped-list">
            {draft.stripped.map((s, i) => (
              <li key={i}>
                {s.text} <span className="subtle">(untraced: {s.numbers.join(', ')})</span>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}
