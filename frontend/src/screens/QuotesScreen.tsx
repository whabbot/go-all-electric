import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, isMockMode, type QuoteCheckResult, type QuoteUploadGroup } from '../api'
import { ImageCoverUp } from '../components/ImageCoverUp'
import { prepareImageFile } from '../lib/imagePrepare'
import { pdfFileToPageImages } from '../lib/pdfToImages'
import { QUOTE_PAGE_GUIDANCE } from '../lib/photoGuidance'

type QuoteQueueItem = {
  url: string
  fileName: string
  sourceLabel: string
  quoteName: string
  quoteIndex: number
}

type RedactedPage = {
  quoteIndex: number
  quoteName: string
  file: File
}

async function buildRedactQueue(files: File[]): Promise<QuoteQueueItem[]> {
  const queue: QuoteQueueItem[] = []
  for (let quoteIndex = 0; quoteIndex < files.length; quoteIndex += 1) {
    const file = files[quoteIndex]
    const isPdf = file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf')
    if (isPdf) {
      const pages = await pdfFileToPageImages(file)
      for (let i = 0; i < pages.length; i += 1) {
        const prepared = await prepareImageFile(pages[i])
        queue.push({
          url: URL.createObjectURL(prepared),
          fileName: prepared.name,
          sourceLabel: `${file.name} page ${i + 1}`,
          quoteName: file.name,
          quoteIndex,
        })
      }
    } else if (file.type.startsWith('image/')) {
      const prepared = await prepareImageFile(file)
      queue.push({
        url: URL.createObjectURL(prepared),
        fileName: prepared.name,
        sourceLabel: file.name,
        quoteName: file.name,
        quoteIndex,
      })
    }
  }
  return queue
}

function groupRedactedPages(pages: RedactedPage[]): QuoteUploadGroup[] {
  const byIndex = new Map<number, QuoteUploadGroup>()
  for (const page of pages) {
    let group = byIndex.get(page.quoteIndex)
    if (!group) {
      group = { quoteName: page.quoteName, pages: [] }
      byIndex.set(page.quoteIndex, group)
    }
    group.pages.push(page.file)
  }
  return [...byIndex.entries()]
    .sort(([a], [b]) => a - b)
    .map(([, group]) => group)
}

export function QuotesScreen() {
  const [redactedPages, setRedactedPages] = useState<RedactedPage[]>([])
  const [results, setResults] = useState<QuoteCheckResult[] | null>(null)
  const [loading, setLoading] = useState(false)
  const [importing, setImporting] = useState(false)
  const [stack, setStack] = useState<QuoteQueueItem[]>([])
  const [current, setCurrent] = useState<QuoteQueueItem | null>(null)
  const [importError, setImportError] = useState<string | null>(null)

  const quoteGroups = useMemo(() => groupRedactedPages(redactedPages), [redactedPages])

  useEffect(() => {
    return () => {
      for (const item of stack) URL.revokeObjectURL(item.url)
      if (current?.url) URL.revokeObjectURL(current.url)
    }
  }, [stack, current])

  const runCheck = async (groups: QuoteUploadGroup[]) => {
    if (groups.length === 0) return
    setLoading(true)
    try {
      const out = await api.checkQuotes(groups)
      setResults(out)
    } finally {
      setLoading(false)
    }
  }

  const startRedactFlow = async (picked: File[]) => {
    setImportError(null)
    setResults(null)
    setRedactedPages([])
    if (current?.url) URL.revokeObjectURL(current.url)
    for (const item of stack) URL.revokeObjectURL(item.url)
    setCurrent(null)
    setStack([])
    setImporting(true)
    try {
      const queue = await buildRedactQueue(picked)
      if (queue.length === 0) {
        setImportError('No pages to redact.')
        return
      }
      const [first, ...rest] = queue
      setCurrent(first)
      setStack(rest)
    } catch {
      setImportError('Could not read that PDF or image.')
    } finally {
      setImporting(false)
    }
  }

  const onUpload = (list: FileList | null) => {
    if (!list) return
    const picked = Array.from(list).slice(0, 3)
    void startRedactFlow(picked)
  }

  const finishPage = (redacted: File) => {
    if (current) {
      setRedactedPages((prev) => [
        ...prev,
        { quoteIndex: current.quoteIndex, quoteName: current.quoteName, file: redacted },
      ])
    }
    if (current?.url) URL.revokeObjectURL(current.url)
    if (stack.length === 0) {
      setCurrent(null)
      return
    }
    const [next, ...rest] = stack
    setCurrent(next)
    setStack(rest)
  }

  const cancelCoverUp = () => {
    if (current?.url) URL.revokeObjectURL(current.url)
    for (const item of stack) URL.revokeObjectURL(item.url)
    setCurrent(null)
    setStack([])
    setRedactedPages([])
  }

  const allPagesReady = redactedPages.length > 0 && !current && stack.length === 0

  const loadSamDemoQuotes = () => {
    const names = ['installer-a-9kw.pdf', 'installer-b-12kw.pdf', 'installer-c-6kw.pdf']
    const groups = names.map(
      (name) => ({
        quoteName: name,
        pages: [new File(['%PDF-1.4'], name, { type: 'application/pdf' })],
      }),
    )
    setRedactedPages(
      groups.map((g, quoteIndex) => ({
        quoteIndex,
        quoteName: g.quoteName,
        file: g.pages[0],
      })),
    )
    void runCheck(groups)
  }

  return (
    <section className="screen quotes-screen">
      <h1>Quote checker</h1>
      <p className="lede">
        Upload up to three installer quotes (PDF or photo). Each page is redacted on your device
        before anything is sent. Flags are prompts for questions — not sent to anyone.
      </p>

      <label className="upload-btn card">
        <input
          type="file"
          accept=".pdf,application/pdf,image/*"
          multiple
          onChange={(e) => onUpload(e.target.files)}
        />
        Choose PDFs or photos (max 3)
      </label>

      {importing && <p className="subhead">Preparing pages for redaction…</p>}
      {importError && <p className="warning">{importError}</p>}

      {quoteGroups.length > 0 && (
        <ul className="file-list">
          {quoteGroups.map((g) => (
            <li key={g.quoteName}>
              {g.quoteName}
              {g.pages.length > 1 ? ` (${g.pages.length} redacted pages)` : ''}
            </li>
          ))}
        </ul>
      )}

      <button
        type="button"
        className="btn primary"
        disabled={!allPagesReady || loading}
        onClick={() => void runCheck(quoteGroups)}
      >
        {loading ? 'Checking…' : 'Check quotes'}
      </button>

      {isMockMode() && (
        <button type="button" className="btn" disabled={loading} onClick={loadSamDemoQuotes}>
          Load Sam&apos;s three quotes (demo)
        </button>
      )}

      {current && (
        <ImageCoverUp
          imageUrl={current.url}
          title={`Redact quote page — ${current.sourceLabel}`}
          guidance={QUOTE_PAGE_GUIDANCE}
          fileName={current.fileName}
          onConfirm={finishPage}
          onCancel={cancelCoverUp}
        />
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
