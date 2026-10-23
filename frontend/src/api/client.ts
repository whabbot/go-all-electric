import {
  SAM_EPC_ADDRESSES,
  SAM_QUOTE_CHECKS,
  mockAnalysisEvents,
  mockPhotoCheck,
  mockReview,
} from './samMocks'
import type {
  AnalysisEvent,
  AnalysisResult,
  EpcAddress,
  PhotoCheckResult,
  PhotoKind,
  QuoteCheckResult,
  QuoteSizeContext,
  QuoteUploadGroup,
  ReviewQuote,
  ReviewResult,
} from './types'

/** Defaults to mocks when unset so production builds work without a backend. */
export const isMockMode = () => {
  const flag = import.meta.env.VITE_USE_MOCKS
  if (flag === 'false' || flag === '0') return false
  return true
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

async function mockDelay(min = 400, max = 900): Promise<void> {
  const ms = min + Math.random() * (max - min)
  await delay(ms)
}

/** FastAPI errors carry `detail`; show it when it is a plain sentence. */
async function failure(res: Response, what: string): Promise<Error> {
  try {
    const body = (await res.json()) as { detail?: unknown }
    if (typeof body.detail === 'string') return new Error(body.detail)
  } catch {
    /* not JSON */
  }
  return new Error(`${what} failed (${res.status})`)
}

export async function searchEpcAddresses(postcode: string): Promise<EpcAddress[]> {
  if (isMockMode()) {
    await mockDelay(300, 700)
    const normalised = postcode.replace(/\s+/g, '').toUpperCase()
    if (normalised.length < 5) return []
    return SAM_EPC_ADDRESSES.filter((a) =>
      a.postcode.replace(/\s+/g, '').toUpperCase().startsWith(normalised.slice(0, 4)),
    )
  }
  const res = await fetch(`/api/epc/search?postcode=${encodeURIComponent(postcode)}`)
  if (!res.ok) throw await failure(res, 'EPC search')
  const body = (await res.json()) as { addresses: EpcAddress[] }
  return body.addresses
}

export async function checkPhoto(kind: PhotoKind, file: File): Promise<PhotoCheckResult> {
  if (isMockMode()) {
    await mockDelay(600, 1400)
    const blurry = file.name.toLowerCase().includes('blur')
    return mockPhotoCheck(kind, blurry)
  }
  const form = new FormData()
  form.append('kind', kind)
  form.append('file', file)
  const res = await fetch('/api/photos/check', { method: 'POST', body: form })
  if (!res.ok) throw await failure(res, 'Photo check')
  return res.json() as Promise<PhotoCheckResult>
}

/**
 * One analysis call: EPC record, every photo and the bill (optional), weather, then the maths.
 * Progress and verification-log entries arrive through `onEvent` as they happen.
 */
export async function runAnalysis(
  certificateId: string,
  files: Partial<Record<PhotoKind, File>>,
  onEvent: (event: AnalysisEvent) => void,
): Promise<AnalysisResult> {
  if (isMockMode()) {
    let result: AnalysisResult | null = null
    for (const event of mockAnalysisEvents(Object.keys(files) as PhotoKind[])) {
      await delay(event.type === 'log' ? 260 : 120)
      onEvent(event)
      if (event.type === 'result') result = event.result
    }
    if (!result) throw new Error('Analysis failed')
    return result
  }
  const form = new FormData()
  form.append('certificate_id', certificateId)
  for (const [kind, file] of Object.entries(files)) if (file) form.append(kind, file)
  const res = await fetch('/api/analysis', { method: 'POST', body: form })
  if (!res.ok || !res.body) throw await failure(res, 'Analysis')

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let outcome: AnalysisEvent | null = null
  const handle = (line: string) => {
    if (!line.trim()) return
    const event = JSON.parse(line) as AnalysisEvent
    onEvent(event)
    if (event.type === 'result' || event.type === 'error') outcome = event
  }
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() ?? ''
    lines.forEach(handle)
  }
  handle(buffer)
  const final = outcome as AnalysisEvent | null
  if (final?.type === 'result') return final.result
  if (final?.type === 'error') throw new Error(final.message)
  throw new Error('The analysis stopped before it finished; try again.')
}

export async function checkQuotes(
  groups: QuoteUploadGroup[],
  size: QuoteSizeContext | null,
): Promise<QuoteCheckResult[]> {
  if (isMockMode()) {
    await mockDelay(1000, 1800)
    return groups.map((g, i) => {
      const base = SAM_QUOTE_CHECKS[i % SAM_QUOTE_CHECKS.length]
      return { ...base, filename: g.quoteName || base.filename }
    })
  }
  const form = new FormData()
  groups.forEach((group, quoteIndex) => {
    for (const file of group.pages) {
      form.append('quotes', file)
      form.append('quote_index', String(quoteIndex))
      form.append('quote_name', group.quoteName)
    }
  })
  if (size) {
    form.append('size_low_kw', String(size.size_low_kw))
    form.append('size_high_kw', String(size.size_high_kw))
    if (size.design_load_kw != null) form.append('design_load_kw', String(size.design_load_kw))
  }
  const res = await fetch('/api/quotes/check', { method: 'POST', body: form })
  if (!res.ok) throw await failure(res, 'Quote check')
  return res.json() as Promise<QuoteCheckResult[]>
}

/** The one-context Gemini 4 Argon review. Sends readings and the bundle, never the address. */
export async function reviewAnalysis(
  analysis: AnalysisResult,
  files: Partial<Record<PhotoKind, File>>,
  quotes: ReviewQuote[],
): Promise<ReviewResult> {
  if (isMockMode()) {
    await mockDelay(4000, 6000)
    return mockReview(quotes.map((q) => q.quote_id))
  }
  const reading = (kind: PhotoKind) => analysis.readings.find((r) => r.kind === kind)?.reading ?? null
  const context = {
    bundle: analysis.bundle,
    epc: analysis.epc,
    boiler: reading('boiler_plate'),
    bill: reading('gas_bill'),
    quotes: quotes.map((q) => ({ quote_id: q.quote_id, reading: q.reading })),
  }
  const form = new FormData()
  form.append('context', JSON.stringify(context))
  for (const [kind, file] of Object.entries(files)) if (file) form.append(kind, file)
  quotes.forEach((q, quoteIndex) => {
    for (const page of q.pages) {
      form.append('quotes', page)
      form.append('quote_index', String(quoteIndex))
    }
  })
  const res = await fetch('/api/analysis/review', { method: 'POST', body: form })
  if (!res.ok) throw await failure(res, 'Review')
  return res.json() as Promise<ReviewResult>
}

export const api = {
  searchEpcAddresses,
  checkPhoto,
  runAnalysis,
  checkQuotes,
  reviewAnalysis,
}
