import {
  SAM_EPC_ADDRESSES,
  SAM_QUOTE_CHECKS,
  mockAnalysisEvents,
  mockInstallerDrafts,
  mockPhotoCheck,
  mockRadiatorVideo,
  mockReview,
} from './samMocks'
import type {
  AnalysisEvent,
  AnalysisResult,
  EpcAddress,
  InstallerDraftsRequest,
  InstallerDraftsResult,
  KnownBoiler,
  KnownDetails,
  KnownFuse,
  PhotoCheckResult,
  PhotoKind,
  QuoteCheckResult,
  QuoteSizeContext,
  QuoteUploadGroup,
  RadiatorUpload,
  RadiatorVideoResult,
  ReviewQuote,
  ReviewResult,
} from './types'

/** The session lives in an HttpOnly cookie set by `/api/session`; script never sees it. */
export async function apiFetch(input: RequestInfo | URL, init: RequestInit = {}): Promise<Response> {
  const response = await fetch(input, { ...init, credentials: 'same-origin' })
  if (response.status === 401) window.dispatchEvent(new Event('gae-access-required'))
  return response
}

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
  const res = await apiFetch('/api/epc/search', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ postcode }),
  })
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
  const res = await apiFetch('/api/photos/check', { method: 'POST', body: form })
  if (!res.ok) throw await failure(res, 'Photo check')
  return res.json() as Promise<PhotoCheckResult>
}

export async function checkRadiatorVideo(
  file: File,
  designLoadKw?: number | null,
): Promise<RadiatorVideoResult> {
  if (isMockMode()) {
    await mockDelay(1200, 2200)
    return mockRadiatorVideo()
  }
  const form = new FormData()
  form.append('file', file)
  if (designLoadKw != null) form.append('design_load_kw', String(designLoadKw))
  const res = await apiFetch('/api/radiators/video', { method: 'POST', body: form })
  if (!res.ok) throw await failure(res, 'Radiator video check')
  return res.json() as Promise<RadiatorVideoResult>
}

/** Each radiator photo goes with the number of the radiator it shows (0 = radiator 1). */
function appendRadiators(form: FormData, radiators: RadiatorUpload[]) {
  radiators.forEach((radiator, index) => {
    for (const photo of radiator.photos) {
      form.append('radiators', photo)
      form.append('radiator_index', String(index))
    }
  })
}

export type KnownExtras = { boiler: KnownBoiler | null; fuse_cutout: KnownFuse | null }

/**
 * One analysis call: EPC record, every photo and the bill (optional), weather, then the maths.
 * Radiators are numbered in order; each may have several photos and entered details. Room
 * labels are not part of `RadiatorUpload`, so they are never sent. Progress and
 * verification-log entries arrive through `onEvent` as they happen.
 */
export async function runAnalysis(
  certificateId: string,
  files: Partial<Record<PhotoKind, File>>,
  onEvent: (event: AnalysisEvent) => void,
  radiatorVideo?: File | null,
  radiators: RadiatorUpload[] = [],
  extras: KnownExtras = { boiler: null, fuse_cutout: null },
): Promise<AnalysisResult> {
  const known: KnownDetails = {
    radiators: radiators.map((r) => r.known),
    boiler: extras.boiler,
    fuse_cutout: extras.fuse_cutout,
  }
  const activeKinds = new Set<PhotoKind>(
    (Object.entries(files) as [PhotoKind, File | undefined][])
      .filter(([k, f]) => Boolean(f) && k !== 'radiators')
      .map(([k]) => k),
  )
  const radiatorActivity = radiators.some(
    (r) => r.photos.length > 0 || Object.keys(r.known).length > 0,
  )
  if (radiatorActivity) activeKinds.add('radiators')
  if (isMockMode()) {
    let result: AnalysisResult | null = null
    for (const event of mockAnalysisEvents(Array.from(activeKinds), Boolean(radiatorVideo), radiators, known)) {
      await delay(event.type === 'log' ? 260 : 120)
      onEvent(event)
      if (event.type === 'result') result = event.result
    }
    if (!result) throw new Error('Analysis failed')
    return result
  }
  const form = new FormData()
  form.append('certificate_id', certificateId)
  for (const [kind, file] of Object.entries(files)) {
    if (kind === 'radiators') continue
    if (file) form.append(kind, file)
  }
  appendRadiators(form, radiators)
  if (radiators.length > 0 || known.boiler || known.fuse_cutout) form.append('known', JSON.stringify(known))
  if (radiatorVideo) form.append('radiator_video', radiatorVideo)
  const res = await apiFetch('/api/analysis', { method: 'POST', body: form })
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
  const res = await apiFetch('/api/quotes/check', { method: 'POST', body: form })
  if (!res.ok) throw await failure(res, 'Quote check')
  return res.json() as Promise<QuoteCheckResult[]>
}

/** What the review sees of hand-entered values: each one, with the photo reading if it disagreed. */
export function enteredForReview(analysis: AnalysisResult) {
  return analysis.readings.flatMap((r) =>
    Object.entries(r.entered ?? {}).map(([field, entered]) => {
      const photoRead = r.disagreements?.find((d) => d.field === field)?.read
      return {
        input: r.kind,
        ...(r.kind === 'radiators' && r.index != null ? { radiator: r.index + 1 } : {}),
        field,
        entered,
        ...(photoRead != null ? { photo_read: photoRead } : {}),
      }
    }),
  )
}

/** The one-context Gemini 4 Argon review. Sends readings and the bundle, never the address. */
export async function reviewAnalysis(
  analysis: AnalysisResult,
  files: Partial<Record<PhotoKind, File>>,
  quotes: ReviewQuote[],
  radiators: RadiatorUpload[] = [],
): Promise<ReviewResult> {
  if (isMockMode()) {
    await mockDelay(4000, 6000)
    return mockReview(quotes.map((q) => q.quote_id))
  }
  // Photo readings only (with entered values applied). Entered-only items reach the review
  // through `entered`, since they are not a full reading.
  const usable = (r: { status: string }) => r.status === 'verified' || r.status === 'verified_with_warnings'
  const reading = (kind: PhotoKind) => {
    const item = analysis.readings.find((r) => r.kind === kind)
    return item && usable(item) ? item.reading : null
  }
  const radiatorItems = analysis.readings.filter((r) => r.kind === 'radiators' && r.index != null)
  const radiatorCount = Math.max(0, ...radiatorItems.map((r) => (r.index ?? 0) + 1))
  // By position: radiator 1 first, null where nothing was read, so photos and readings line up.
  const radiatorReadings = Array.from(
    { length: radiatorCount },
    (_, i) => radiatorItems.find((r) => r.index === i && usable(r))?.reading ?? null,
  )
  const context = {
    bundle: analysis.bundle,
    epc: analysis.epc,
    boiler: reading('boiler_plate'),
    bill: reading('gas_bill'),
    radiators: radiatorCount > 0 ? radiatorReadings : null,
    radiator_video: analysis.radiator_video ?? null,
    fuse_cutout: reading('fuse_cutout'),
    outdoor_space: reading('outdoor_space'),
    loft: reading('loft'),
    entered: enteredForReview(analysis),
    quotes: quotes.map((q) => ({ quote_id: q.quote_id, reading: q.reading })),
  }
  const form = new FormData()
  form.append('context', JSON.stringify(context))
  for (const [kind, file] of Object.entries(files)) {
    if (kind === 'radiators') continue
    if (file) form.append(kind, file)
  }
  appendRadiators(form, radiators)
  quotes.forEach((q, quoteIndex) => {
    for (const page of q.pages) {
      form.append('quotes', page)
      form.append('quote_index', String(quoteIndex))
    }
  })
  const res = await apiFetch('/api/analysis/review', { method: 'POST', body: form })
  if (!res.ok) throw await failure(res, 'Review')
  return res.json() as Promise<ReviewResult>
}

/** Gemini 4 Argon drafts one installer email per quote; every number is checked in code. */
export async function draftInstallerEmails(req: InstallerDraftsRequest): Promise<InstallerDraftsResult> {
  if (isMockMode()) {
    await mockDelay(5000, 7000)
    return mockInstallerDrafts(req)
  }
  const res = await apiFetch('/api/pack/installer-drafts', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
  if (!res.ok) throw await failure(res, 'Drafting')
  return res.json() as Promise<InstallerDraftsResult>
}

export const api = {
  searchEpcAddresses,
  checkPhoto,
  checkRadiatorVideo,
  runAnalysis,
  checkQuotes,
  reviewAnalysis,
  draftInstallerEmails,
}
