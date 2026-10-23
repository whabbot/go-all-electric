import { Link } from 'react-router-dom'
import { PackDraft } from '../components/PackDraft'
import { useSession } from '../context/SessionContext'
import {
  buildHouseSummaryDraft,
  buildInstallerQuestionDraft,
  buildNetworkOperatorDraft,
} from '../lib/packTemplates'

function slugFileName(label: string): string {
  return label.replace(/[^a-z0-9]+/gi, '-').replace(/^-|-$/g, '').toLowerCase()
}

export function PackScreen() {
  const { analysis, quotes } = useSession()

  if (!analysis) {
    return (
      <section className="screen pack-screen">
        <h1>Your pack</h1>
        <p className="lede">Run the estimates first — the pack is built from your survey session.</p>
        <p className="cta-row">
          <Link className="btn" to="/estimates">Go to estimates</Link>
        </p>
      </section>
    )
  }

  const checkedQuotes = quotes.filter((q) => q.result != null)

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

      {checkedQuotes.length === 0 ? (
        <p className="card subtle">
          No checked installer quotes yet.{' '}
          <Link to="/quotes">Check quotes</Link> to generate per-installer question drafts.
        </p>
      ) : (
        checkedQuotes.map((q, i) => {
          const result = q.result!
          const label = q.group.quoteName || result.filename
          return (
            <PackDraft
              key={`${label}-${i}`}
              id={`installer-${i}`}
              title={`Questions for ${label}`}
              description="Opening with your target size, flow temperature and measured heat loss; then flags and questions from the quote check."
              initialText={buildInstallerQuestionDraft(result, analysis)}
              downloadFileName={`installer-questions-${slugFileName(label)}.txt`}
            />
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
