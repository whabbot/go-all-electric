import { useEffect, useMemo, useRef, useState } from 'react'
import { api, isMockMode, type QuoteCheckResult, type QuoteSizeContext, type QuoteUploadGroup } from '../api'
import { ImageCoverUp } from '../components/ImageCoverUp'
import { ReviewPanel } from '../components/ReviewPanel'
import { VerificationLogPanel } from '../components/VerificationLog'
import { useSession } from '../context/SessionContext'
import { quoteId } from '../lib/labels'
import { newQuoteId } from '../lib/quoteIdentity'
import { resetFileInput } from '../lib/fileInputReset'
import { prepareImageFile } from '../lib/imagePrepare'
import { pdfFileToPageImages } from '../lib/pdfToImages'
import { CaptureWhyNeedDialog } from '../components/CaptureWhyNeedDialog'
import { WhyNeedTrigger } from '../components/WhyNeedTrigger'
import { QUOTE_PAGE_GUIDANCE } from '../lib/photoGuidance'

type QuoteQueueItem = {
  url: string
  fileName: string
  sourceLabel: string
  quoteId: string
}

type RedactedPage = {
  quoteId: string
  file: File
}

async function buildRedactQueue(files: File[]): Promise<QuoteQueueItem[]> {
  const queue: QuoteQueueItem[] = []
  for (const file of files) {
    const id = newQuoteId()
    const isPdf = file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf')
    if (isPdf) {
      const pages = await pdfFileToPageImages(file)
      for (let i = 0; i < pages.length; i += 1) {
        const prepared = await prepareImageFile(pages[i])
        queue.push({
          url: URL.createObjectURL(prepared),
          fileName: prepared.name,
          sourceLabel: `${file.name} page ${i + 1}`,
          quoteId: id,
        })
      }
    } else if (file.type.startsWith('image/')) {
      const prepared = await prepareImageFile(file)
      queue.push({
        url: URL.createObjectURL(prepared),
        fileName: prepared.name,
        sourceLabel: file.name,
        quoteId: id,
      })
    }
  }
  return queue
}

function groupRedactedPages(pages: RedactedPage[]): Array<{ id: string; pages: File[] }> {
  const byId = new Map<string, File[]>()
  const order: string[] = []
  for (const page of pages) {
    if (!byId.has(page.quoteId)) {
      byId.set(page.quoteId, [])
      order.push(page.quoteId)
    }
    byId.get(page.quoteId)!.push(page.file)
  }
  return order.map((id) => ({ id, pages: byId.get(id)! }))
}

function toUploadGroups(
  grouped: Array<{ id: string; pages: File[] }>,
  results: Map<string, QuoteCheckResult | null>,
): QuoteUploadGroup[] {
  return grouped.map((g, index) => {
    const result = results.get(g.id) ?? null
    return {
      id: g.id,
      quoteName: quoteId(index, result),
      pages: g.pages,
    }
  })
}

/** Size range and design load from the analysis; none without a bill (no measured basis). */
function sizeContext(analysis: ReturnType<typeof useSession>['analysis']): QuoteSizeContext | null {
  if (!analysis?.bundle.measured || analysis.size_basis !== 'measured') return null
  const size = analysis.bundle.target_spec.size_kw
  return {
    size_low_kw: size.low,
    size_high_kw: size.high,
    design_load_kw: analysis.bundle.measured.design_load_kw.central,
  }
}

export function QuotesScreen() {
  const { analysis, quotes, setQuotes, placeLabel, setQuotesStepBlocked } = useSession()
  const [redactedPages, setRedactedPages] = useState<RedactedPage[]>([])
  const [checkError, setCheckError] = useState<string | null>(null)
  const size = sizeContext(analysis)
  const [loading, setLoading] = useState(false)
  const [importing, setImporting] = useState(false)
  const [stack, setStack] = useState<QuoteQueueItem[]>([])
  const [current, setCurrent] = useState<QuoteQueueItem | null>(null)
  const [importError, setImportError] = useState<string | null>(null)
  const [whyNeedOpen, setWhyNeedOpen] = useState(false)
  const whyNeedTriggerRef = useRef<HTMLButtonElement | null>(null)
  const uploadInputRef = useRef<HTMLInputElement | null>(null)

  const quoteGroups = useMemo(
    () =>
      toUploadGroups(
        groupRedactedPages(redactedPages),
        new Map(quotes.map((q) => [q.group.id, q.result])),
      ),
    [quotes, redactedPages],
  )

  const syncQuotesSession = (pages: RedactedPage[]) => {
    const grouped = groupRedactedPages(pages)
    const resultById = new Map(quotes.map((q) => [q.group.id, q.result]))
    setQuotes(toUploadGroups(grouped, resultById).map((group) => ({
      group,
      result: resultById.get(group.id) ?? null,
    })))
  }

  useEffect(() => {
    if (quotes.length === 0 || redactedPages.length > 0) return
    setRedactedPages(
      quotes.flatMap((q) =>
        q.group.pages.map((file) => ({
          quoteId: q.group.id,
          file,
        })),
      ),
    )
  }, [quotes, redactedPages.length])

  const allPagesReady = redactedPages.length > 0 && !current && stack.length === 0

  useEffect(() => {
    const waitingForCheck =
      allPagesReady && quotes.some((q) => q.group.pages.length > 0 && !q.result)
    setQuotesStepBlocked(Boolean(current) || stack.length > 0 || waitingForCheck)
  }, [allPagesReady, current, quotes, setQuotesStepBlocked, stack.length])

  const queueRef = useRef<QuoteQueueItem[]>([])
  useEffect(() => {
    queueRef.current = current ? [current, ...stack] : stack
  }, [stack, current])
  useEffect(() => {
    return () => {
      for (const item of queueRef.current) URL.revokeObjectURL(item.url)
    }
  }, [])

  const runCheck = async (groups: QuoteUploadGroup[]) => {
    if (groups.length === 0) return
    setLoading(true)
    setCheckError(null)
    try {
      const out = await api.checkQuotes(groups, size)
      setQuotes(
        groups.map((group, i) => {
          const result = out[i] ?? null
          return {
            group: { ...group, quoteName: quoteId(i, result) },
            result,
          }
        }),
      )
    } catch (e) {
      setCheckError(e instanceof Error ? e.message : 'Quote check failed')
    } finally {
      setLoading(false)
    }
  }

  const startRedactFlow = async (picked: File[]) => {
    setImportError(null)
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

  const onUpload = (list: FileList | null, input: HTMLInputElement) => {
    const picked = list ? Array.from(list) : []
    resetFileInput(input)
    if (picked.length === 0) return
    const slotsLeft = 3 - quoteGroups.length
    if (slotsLeft <= 0) {
      setImportError('You can upload at most three quotes. Remove one to add another.')
      return
    }
    if (picked.length > slotsLeft) {
      setImportError(`Only ${slotsLeft} quote slot${slotsLeft === 1 ? '' : 's'} left (max 3).`)
      return
    }
    void startRedactFlow(picked.slice(0, slotsLeft))
  }

  const removeQuote = (id: string) => {
    const nextPages = redactedPages.filter((p) => p.quoteId !== id)
    setRedactedPages(nextPages)
    syncQuotesSession(nextPages)
  }

  const finishPage = (redacted: File) => {
    if (current) {
      setRedactedPages((prev) => {
        const next = [...prev, { quoteId: current.quoteId, file: redacted }]
        syncQuotesSession(next)
        return next
      })
    }
    resetFileInput(uploadInputRef.current)
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
    resetFileInput(uploadInputRef.current)
  }

  const loadSamDemoQuotes = () => {
    const groups: QuoteUploadGroup[] = ['Quote A', 'Quote B', 'Quote C'].map((name) => ({
      id: newQuoteId(),
      quoteName: name,
      pages: [new File(['%PDF-1.4'], name, { type: 'application/pdf' })],
    }))
    setRedactedPages(
      groups.map((g) => ({
        quoteId: g.id,
        file: g.pages[0],
      })),
    )
    void runCheck(groups)
  }

  const checkedQuotes = quotes.filter((q) => q.result)

  return (
    <section className="screen quotes-screen">
      <h1>Quotes</h1>
      {placeLabel && <p className="place-label">{placeLabel}</p>}
      <div className="quotes-upload-header">
        <p className="lede">
          Upload up to three installer quotes (PDF or photo). Each page is redacted on your device
          before anything is sent. Flags are prompts for questions — not sent to anyone.
        </p>
        <WhyNeedTrigger
          onActivate={(el) => {
            whyNeedTriggerRef.current = el
            setWhyNeedOpen(true)
          }}
        />
      </div>

      <label className="upload-btn card">
        <input
          ref={uploadInputRef}
          type="file"
          accept=".pdf,application/pdf,image/*"
          multiple
          onChange={(e) => onUpload(e.target.files, e.currentTarget)}
        />
        Choose PDFs or photos (max 3)
      </label>

      {importing && <p className="subhead">Preparing pages for redaction…</p>}
      {importError && <p className="warning">{importError}</p>}

      {quoteGroups.length > 0 && (
        <ul className="file-list">
          {quoteGroups.map((g) => (
            <li key={g.id}>
              {g.quoteName}
              {g.pages.length > 1 ? ` (${g.pages.length} redacted pages)` : ''}
              {!loading && (
                <button type="button" className="btn" onClick={() => removeQuote(g.id)}>
                  Remove
                </button>
              )}
            </li>
          ))}
        </ul>
      )}

      <div className="btn-row">
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
      </div>

      {loading && (
        <div className="quote-check-loading" role="status" aria-live="polite">
          <span className="inline-spinner" aria-hidden="true" />
          Checking your quotes against your target size…
          <ul className="quote-skeleton-list">
            {quoteGroups.map((g) => (
              <li key={g.id} className="card quote-skeleton-card" aria-hidden="true" />
            ))}
          </ul>
        </div>
      )}

      {current && (
        <ImageCoverUp
          key={current.url}
          imageUrl={current.url}
          title={`Redact quote page — ${current.sourceLabel}`}
          guidance={QUOTE_PAGE_GUIDANCE}
          fileName={current.fileName}
          onConfirm={finishPage}
          onCancel={cancelCoverUp}
        />
      )}

      {size ? (
        <p className="subtle">
          Checked against your target size {size.size_low_kw}–{size.size_high_kw} kW (bills say about{' '}
          {size.design_load_kw?.toFixed(1)} kW).
        </p>
      ) : (
        <p className="subtle">
          {analysis
            ? 'No measured estimate (no usable bill), so quotes are not size-checked; flow, buffer and grant are.'
            : 'Run the estimates first to check quote sizes against your bills.'}
        </p>
      )}
      {whyNeedOpen && (
        <CaptureWhyNeedDialog
          id="installer_quotes"
          returnFocusTo={whyNeedTriggerRef.current}
          onClose={() => setWhyNeedOpen(false)}
        />
      )}

      {checkError && <p className="error">{checkError}</p>}

      {checkedQuotes.length > 0 && (
        <div className="quote-results">
          {checkedQuotes.map((q) => {
            const result = q.result!
            return (
              <article key={q.group.id} className="card quote-card">
                <h2>{q.group.quoteName}</h2>
                {result.verified.status === 'couldnt_tell' && (
                  <p className="warning">Couldn&apos;t read this quote reliably.</p>
                )}
                {result.quoted_kw != null && <p>Quoted size: {result.quoted_kw} kW</p>}
                {result.design_flow_temp_c != null && <p>Design flow: {result.design_flow_temp_c} °C</p>}
                <ul className="flags">
                  {result.flags.map((f, i) => (
                    <li key={i} className={`flag flag-${f.severity}`}>
                      <strong>
                        {f.severity === 'red' ? 'Issue: ' : f.severity === 'amber' ? 'Caution: ' : 'Info: '}
                        {f.message}
                      </strong>
                      <span className="evidence">{f.evidence}</span>
                    </li>
                  ))}
                </ul>
                <h3>Questions to ask before signing</h3>
                <ul>
                  {result.questions_to_ask.map((question) => (
                    <li key={question}>{question}</li>
                  ))}
                </ul>
              </article>
            )
          })}
        </div>
      )}

      {checkedQuotes.length > 0 && (
        <VerificationLogPanel
          title="Quote reading log"
          entries={checkedQuotes.flatMap((q, i) =>
            (q.result?.verified.log ?? []).map((e) => ({ ...e, id: `q${i}-${e.id}` })),
          )}
        />
      )}

      <ReviewPanel />
    </section>
  )
}
