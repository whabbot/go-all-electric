import { useCallback, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { DraftProvenance, GeminiDraftsPanel, type DraftingState } from '../components/GeminiDrafts'
import { PackDraft } from '../components/PackDraft'
import { useSession } from '../context/SessionContext'
import { quoteId } from '../lib/labels'
import {
  buildHouseSummaryDraft,
  buildInstallerDraftsRequest,
  buildInstallerQuestionDraft,
  buildNetworkOperatorDraft,
} from '../lib/packTemplates'

function slugFileName(label: string): string {
  return label.replace(/[^a-z0-9]+/gi, '-').replace(/^-|-$/g, '').toLowerCase()
}

export function PackScreen() {
  const { analysis, quotes } = useSession()
  const [drafting, setDrafting] = useState<DraftingState>({ status: 'idle' })
  // Labels whose Gemini draft the homeowner swapped back to the template.
  const [templateFor, setTemplateFor] = useState<Record<string, boolean>>({})
  const run = useRef(0)

  // Labelled by position in the session's quote list, like the review: never by file name.
  const checkedQuotes = quotes
    .map((q, i) => ({ q, label: quoteId(i, q.result) }))
    .filter((x) => x.q.result != null)

  const startDrafting = useCallback(() => {
    if (!analysis || checkedQuotes.length === 0) return
    const id = ++run.current
    const startedAt = Date.now()
    setDrafting({ status: 'running', startedAt })
    setTemplateFor({})
    api
      .draftInstallerEmails(
        buildInstallerDraftsRequest(
          analysis,
          checkedQuotes.map(({ q, label }) => ({ label, result: q.result! })),
        ),
      )
      .then((result) => {
        if (id === run.current)
          setDrafting({ status: 'done', result, startedAt, elapsedMs: Date.now() - startedAt })
      })
      .catch((e: unknown) => {
        if (id === run.current)
          setDrafting({ status: 'failed', message: e instanceof Error ? e.message : 'Drafting failed.' })
      })
  }, [analysis, checkedQuotes])

  if (!analysis) return null

  const drafts = drafting.status === 'done' ? drafting.result.drafts : []

  return (
    <section className="screen pack-screen">
      <h1>Your pack</h1>
      <p className="lede">
        Editable drafts you copy or download yourself. Nothing is sent from this app — you choose who
        gets these.
      </p>
      <p className="subtle pack-privacy">
        No address, name, or meter details are included. Use <strong>[your address]</strong> where
        you need to fill in your own.
      </p>

      {checkedQuotes.length > 0 && (
        <GeminiDraftsPanel quoteCount={checkedQuotes.length} state={drafting} onDraft={startDrafting} />
      )}

      {checkedQuotes.length === 0 ? (
        <p className="card subtle">
          No checked installer quotes yet.{' '}
          <Link to="/quotes">Check quotes</Link> to generate per-installer question drafts.
        </p>
      ) : (
        checkedQuotes.map(({ q, label: quoteLabel }, i) => {
          const result = q.result!
          const label = q.group.quoteName || result.filename
          const draft = drafts.find((d) => d.quote_label === quoteLabel)
          const useDraft = draft != null && !templateFor[quoteLabel]
          // A checked Gemini draft (or the backend's template, which names right-sized models)
          // replaces the local template; remounting resets the "I've reviewed this" gate.
          const text = useDraft
            ? `Subject: ${draft.subject}\n\n${draft.text}`
            : buildInstallerQuestionDraft(result, analysis)
          const version = drafting.status === 'done' ? drafting.startedAt : 0
          return (
            <PackDraft
              key={`${label}-${i}-${version}-${useDraft ? 'drafted' : 'template'}`}
              id={`installer-${i}`}
              title={`Questions for ${label}`}
              description="Opening with your target size, flow temperature and measured heat loss; then flags and questions from the quote check."
              initialText={text}
              downloadFileName={`installer-questions-${slugFileName(label)}.txt`}
            >
              {draft && (
                <DraftProvenance
                  draft={draft}
                  showingGemini={useDraft}
                  onToggle={() => setTemplateFor((prev) => ({ ...prev, [quoteLabel]: !prev[quoteLabel] }))}
                />
              )}
            </PackDraft>
          )
        })
      )}

      <PackDraft
        id="house-summary"
        title="House summary for installers"
        description="Measured and fabric estimates, cross-check, target spec, fuse and grant — every figure shows its range or confidence and source."
        initialText={buildHouseSummaryDraft(analysis)}
        downloadFileName="house-summary-for-installers.txt"
      />

      <PackDraft
        id="dno-note"
        title="Draft note to network operator"
        description="Heat pump size (and EV charger if planned) against your fuse reading — an enquiry only, not an application."
        initialText={buildNetworkOperatorDraft(analysis)}
        downloadFileName="network-operator-draft-note.txt"
      />

      <blockquote className="advice-quote">It advises; you decide.</blockquote>

      <p className="cta-row">
        <Link className="btn" to="/plan">Back to plan</Link>
        <Link className="btn" to="/quotes">Quote checker</Link>
      </p>
    </section>
  )
}
