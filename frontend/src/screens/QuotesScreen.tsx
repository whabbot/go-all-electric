import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api, isMockMode, type QuoteCheckResult } from '../api'

export function QuotesScreen() {
  const [files, setFiles] = useState<File[]>([])
  const [results, setResults] = useState<QuoteCheckResult[] | null>(null)
  const [loading, setLoading] = useState(false)

  const onUpload = (list: FileList | null) => {
    if (!list) return
    const picked = Array.from(list).slice(0, 3)
    setFiles(picked)
    setResults(null)
  }

  const runCheck = async (picked: File[]) => {
    if (picked.length === 0) return
    setLoading(true)
    try {
      const out = await api.checkQuotes(picked)
      setResults(out)
    } finally {
      setLoading(false)
    }
  }

  const loadSamDemoQuotes = () => {
    const demo = ['installer-a-9kw.pdf', 'installer-b-12kw.pdf', 'installer-c-6kw.pdf'].map(
      (name) => new File(['%PDF-1.4'], name, { type: 'application/pdf' }),
    )
    setFiles(demo)
    void runCheck(demo)
  }

  return (
    <section className="screen quotes-screen">
      <h1>Quote checker</h1>
      <p className="lede">Upload up to three installer quotes (PDF). Flags are prompts for questions — not sent to anyone.</p>

      <label className="upload-btn card">
        <input type="file" accept=".pdf,application/pdf" multiple onChange={(e) => onUpload(e.target.files)} />
        Choose PDFs (max 3)
      </label>

      {files.length > 0 && (
        <ul className="file-list">
          {files.map((f) => (
            <li key={f.name}>{f.name}</li>
          ))}
        </ul>
      )}

      <button
        type="button"
        className="btn primary"
        disabled={files.length === 0 || loading}
        onClick={() => void runCheck(files)}
      >
        {loading ? 'Checking…' : 'Check quotes'}
      </button>

      {isMockMode() && (
        <button type="button" className="btn" disabled={loading} onClick={loadSamDemoQuotes}>
          Load Sam&apos;s three quotes (demo)
        </button>
      )}

      {results && (
        <div className="quote-results">
          {results.map((q) => (
            <article key={q.filename} className="card quote-card">
              <h2>{q.filename}</h2>
              {q.quoted_kw != null && <p>Quoted size: {q.quoted_kw} kW</p>}
              {q.design_flow_temp_c != null && <p>Design flow: {q.design_flow_temp_c} °C</p>}
              <ul className="flags">
                {q.flags.map((f, i) => (
                  <li key={i} className={`flag flag-${f.severity}`}>
                    <strong>{f.message}</strong>
                    <span className="evidence">{f.evidence}</span>
                  </li>
                ))}
              </ul>
              <h3>Questions to ask before signing</h3>
              <ul>
                {q.questions_to_ask.map((question) => (
                  <li key={question}>{question}</li>
                ))}
              </ul>
            </article>
          ))}
        </div>
      )}

      <p className="cta-row">
        <Link className="btn" to="/plan">See full plan</Link>
      </p>
    </section>
  )
}
