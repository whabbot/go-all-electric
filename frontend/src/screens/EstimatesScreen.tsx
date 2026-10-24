import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, isMockMode, type AnalysisResult, type PhotoKind, type VerificationLogEntry } from '../api'
import { EstimateHero } from '../components/EstimateHero'
import { RadiatorVideoResults } from '../components/RadiatorVideoResults'
import { ReviewPanel } from '../components/ReviewPanel'
import { VerificationLogPanel } from '../components/VerificationLog'
import { useSession } from '../context/SessionContext'

const STEP_LABELS: Record<string, string> = {
  epc: 'EPC record',
  read_boiler_plate: 'Boiler data plate',
  read_radiators: 'Radiators',
  read_radiator_video: 'Radiator walkthrough video',
  read_fuse_cutout: 'Fuse cutout',
  read_outdoor_space: 'Outdoor unit spot',
  read_loft: 'Loft',
  read_gas_bill: 'Gas bill',
  weather: 'Weather for your bill dates',
  save: 'Save survey (district only)',
}

const STATUS_LABEL: Record<string, string> = {
  verified: 'verified',
  verified_with_warnings: 'verified, with warnings',
  couldnt_tell: "couldn't tell",
  not_provided: 'not provided',
}

/** Photos the answer does not depend on: skipping them is never shown as a gap. */
const OPTIONAL_KINDS: PhotoKind[] = ['outdoor_space', 'loft']

type Progress = Record<string, { status: 'running' | 'done'; ms: number | null }>

function formatValue(value: unknown): string | null {
  if (value == null || value === '' || (Array.isArray(value) && value.length === 0)) return null
  if (Array.isArray(value)) return value.every((v) => typeof v === 'string') ? value.join(', ') : null
  if (typeof value === 'object') return null
  return String(value)
}

function ReadingValues({ reading }: { reading: Record<string, unknown> }) {
  const shown = Object.entries(reading)
    .filter(([k]) => !['notes', 'legible', 'confidence', 'monthly', 'line_items'].includes(k))
    .map(([k, v]) => [k, formatValue(v)] as const)
    .filter(([, v]) => v != null)
  if (shown.length === 0) return null
  return (
    <p className="subtle">
      {shown.map(([k, v]) => `${k.replaceAll('_', ' ')}: ${v}`).join(' · ')}
      {typeof reading.confidence === 'string' && ` · confidence ${reading.confidence}`}
    </p>
  )
}

function Inputs({ analysis }: { analysis: AnalysisResult }) {
  return (
    <>
      {analysis.gaps.length > 0 && (
        <section className="card">
          <h2>Couldn&apos;t tell</h2>
          <ul className="gap-list">
            {analysis.gaps.map((g, i) => (
              <li key={i}>
                <strong>{g.input.replaceAll('_', ' ')}:</strong> {g.message}
                <p className="provide">What to provide: {g.provide}</p>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="card">
        <h2>What we read</h2>
        <ul className="reading-list">
          {analysis.readings.map((r) => (
            <li key={r.kind}>
              <strong>{r.kind.replaceAll('_', ' ')}</strong>
              <span className={`reading-status ${r.status}`}>
                {r.status === 'not_provided' && OPTIONAL_KINDS.includes(r.kind) ? 'optional' : STATUS_LABEL[r.status]}
              </span>
              {r.attempts > 1 && <span className="subtle"> after a re-read</span>}
              {r.reading && <ReadingValues reading={r.reading} />}
              {r.warnings.length > 0 && <p className="subtle">Warnings: {r.warnings.join('; ')}</p>}
              {r.status === 'couldnt_tell' && r.photograph_instead && (
                <p className="subtle">Photograph instead: {r.photograph_instead}</p>
              )}
              {r.used_for && <p className="subtle">Used for: {r.used_for}</p>}
            </li>
          ))}
        </ul>
      </section>

      {analysis.radiator_video && (
        <section className="card">
          <h2>Radiator walkthrough video</h2>
          <RadiatorVideoResults result={analysis.radiator_video} />
        </section>
      )}

      {analysis.defaults.length > 0 && (
        <section className="card">
          <h2>Named defaults</h2>
          <p className="subtle">Where we had no reading, this is what the maths assumed. Nothing is invented silently.</p>
          <ul className="default-list">
            {analysis.defaults.map((d, i) => (
              <li key={i}>
                <strong>{d.name.replaceAll('_', ' ')}</strong> = {d.value}{' '}
                <span className={`conf conf-${d.confidence}`}>{d.confidence}</span>
                <br />
                <span className="subtle">{d.note}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  )
}

export function EstimatesScreen() {
  const { address, placeLabel, analysis, setAnalysis, files, radiatorVideo } = useSession()
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [progress, setProgress] = useState<Progress>({})
  const [liveLog, setLiveLog] = useState<VerificationLogEntry[]>([])
  const started = useRef(false)
  const canRun = Boolean(address) || isMockMode()

  const run = () => {
    setRunning(true)
    setError(null)
    setProgress({})
    setLiveLog([])
    const certificate = address?.certificate_id ?? 'sam-demo'
    api
      .runAnalysis(
        certificate,
        files,
        (event) => {
          if (event.type === 'step') {
            setProgress((p) => ({ ...p, [event.step]: { status: event.status, ms: event.ms } }))
          } else if (event.type === 'log') {
            setLiveLog((log) => [...log, event.entry])
          }
        },
        radiatorVideo,
      )
      .then(setAnalysis)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : 'Analysis failed'))
      .finally(() => setRunning(false))
  }

  useEffect(() => {
    // One run per visit (also under StrictMode's double effect); re-run is explicit.
    if (analysis || started.current || !canRun) return
    started.current = true
    run()
    // eslint-disable-next-line react-hooks/exhaustive-deps -- run once when there is no analysis
  }, [analysis, canRun])

  if (!canRun) {
    return (
      <p className="warning">
        Pick a house on <Link to="/">Start</Link> first.
      </p>
    )
  }

  if (running || (!analysis && !error)) {
    return (
      <section className="screen estimates-screen">
        <h1>Checking your house</h1>
        {placeLabel && <p className="place-label">{placeLabel}</p>}
        <ul className="progress-list" aria-live="polite">
          {Object.entries(progress).map(([step, p]) => (
            <li key={step}>
              <span>{STEP_LABELS[step] ?? step}</span>
              <span className={p.status}>
                {p.status === 'running' ? 'working…' : `done${p.ms != null ? ` in ${(p.ms / 1000).toFixed(1)}s` : ''}`}
              </span>
            </li>
          ))}
        </ul>
        <VerificationLogPanel title="Verification log (live)" entries={liveLog} live />
      </section>
    )
  }

  if (error || !analysis) {
    return (
      <section className="screen estimates-screen">
        <h1>Two estimates</h1>
        <p className="error">{error}</p>
        <VerificationLogPanel entries={liveLog} />
        <button type="button" className="btn" onClick={run}>
          Try again
        </button>
      </section>
    )
  }

  const billGap = analysis.gaps.find((g) => g.input === 'gas_bill') ?? null

  return (
    <section className="screen estimates-screen">
      <h1>
        Two estimates
        {isMockMode() && <span className="mock-badge">offline demo data</span>}
      </h1>
      {placeLabel && <p className="place-label">{placeLabel}</p>}
      <EstimateHero analysis={analysis.bundle} billGap={billGap} />
      <Inputs analysis={analysis} />
      <ReviewPanel />
      <VerificationLogPanel entries={analysis.log} />
      <p className="subtle">
        {analysis.saved ? 'Survey saved with the postcode district only.' : analysis.storage_note}
      </p>
      <p className="cta-row">
        <button type="button" className="btn" onClick={run}>
          Re-run with current photos
        </button>
        <Link className="btn primary" to={analysis.bundle.costs_by_flow_temp.length ? '/cost' : '/spec'}>
          {analysis.bundle.costs_by_flow_temp.length ? 'Running costs' : 'Target spec'}
        </Link>
      </p>
    </section>
  )
}
