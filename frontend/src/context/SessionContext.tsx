import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from 'react'
import { mockAnalysisResult, SAM_EPC_ADDRESSES } from '../api/samMocks'
import {
  api,
  type AnalysisResult,
  type EpcAddress,
  type PhotoCheckResult,
  type PhotoKind,
  type QuoteCheckResult,
  type QuoteUploadGroup,
  type RadiatorVideoResult,
  type ReviewQuote,
  type ReviewResult,
} from '../api'
import { outwardCode, quoteId } from '../lib/labels'

type PhotoSlot = {
  kind: PhotoKind
  label: string
  result: PhotoCheckResult | null
  fileName: string | null
}

const PHOTO_SLOTS: { kind: PhotoKind; label: string }[] = [
  { kind: 'boiler_plate', label: 'Boiler data plate' },
  { kind: 'radiators', label: 'Radiators' },
  { kind: 'fuse_cutout', label: 'Fuse cutout' },
  { kind: 'outdoor_space', label: 'Outdoor unit spot (optional)' },
  { kind: 'gas_bill', label: 'Gas bill' },
  { kind: 'loft', label: 'Loft (optional)' },
]

export type CheckedQuote = { group: QuoteUploadGroup; result: QuoteCheckResult | null }

export type ConflictDecision = 'confirmed' | 'dismissed'

export type ReviewState =
  | { status: 'idle' }
  | { status: 'running'; startedAt: number }
  | { status: 'done'; result: ReviewResult; elapsedMs: number; quoteCount: number }
  | { status: 'failed'; message: string }

type Session = {
  address: EpcAddress | null
  setAddress: (a: EpcAddress | null) => void
  /** "house in N10": the only location shown once an address is picked. */
  placeLabel: string | null
  photos: PhotoSlot[]
  /** Files stay in memory for this tab only; they are never written to storage. */
  files: Partial<Record<PhotoKind, File>>
  setPhoto: (kind: PhotoKind, file: File | null, result: PhotoCheckResult | null) => void
  radiatorVideo: File | null
  radiatorVideoResult: RadiatorVideoResult | null
  setRadiatorVideo: (file: File | null, result: RadiatorVideoResult | null) => void
  analysis: AnalysisResult | null
  setAnalysis: (a: AnalysisResult | null) => void
  quotes: CheckedQuote[]
  setQuotes: (q: CheckedQuote[]) => void
  review: ReviewState
  startReview: () => void
  /** Confirm/dismiss choices on tested EPC conflicts; kept in session state only. */
  conflictDecisions: Record<string, ConflictDecision>
  setConflictDecision: (key: string, decision: ConflictDecision | null) => void
  samSampleLoaded: boolean
  loadSamSample: () => void
}

const SessionContext = createContext<Session | null>(null)

const STORAGE_KEY = 'gae-analysis-v2'

export function SessionProvider({ children }: { children: ReactNode }) {
  const [address, setAddressState] = useState<EpcAddress | null>(null)
  const [analysis, setAnalysisState] = useState<AnalysisResult | null>(() => {
    try {
      const raw = sessionStorage.getItem(STORAGE_KEY)
      return raw ? (JSON.parse(raw) as AnalysisResult) : null
    } catch {
      return null
    }
  })
  const [files, setFiles] = useState<Partial<Record<PhotoKind, File>>>({})
  const [checks, setChecks] = useState<Partial<Record<PhotoKind, PhotoCheckResult | null>>>({})
  const [radiatorVideo, setRadiatorVideoFile] = useState<File | null>(null)
  const [radiatorVideoResult, setRadiatorVideoResult] = useState<RadiatorVideoResult | null>(null)
  const [quotes, setQuotesState] = useState<CheckedQuote[]>([])
  const [review, setReview] = useState<ReviewState>({ status: 'idle' })
  const [conflictDecisions, setConflictDecisions] = useState<Record<string, ConflictDecision>>({})
  const [samSampleLoaded, setSamSampleLoaded] = useState(false)
  const reviewRun = useRef(0)

  const setAnalysis = useCallback((a: AnalysisResult | null) => {
    setAnalysisState(a)
    reviewRun.current += 1
    setReview({ status: 'idle' })
    setConflictDecisions({})
    try {
      // The result carries the postcode district only, never the address.
      if (a) sessionStorage.setItem(STORAGE_KEY, JSON.stringify(a))
      else sessionStorage.removeItem(STORAGE_KEY)
    } catch {
      /* private mode / storage full */
    }
  }, [])

  const setAddress = useCallback(
    (a: EpcAddress | null) => {
      setAddressState(a)
      setAnalysis(null)
    },
    [setAnalysis],
  )

  const loadSamSample = useCallback(() => {
    setSamSampleLoaded(true)
    setAddressState(SAM_EPC_ADDRESSES[0])
    setAnalysis(
      mockAnalysisResult(['boiler_plate', 'radiators', 'fuse_cutout', 'gas_bill'], false),
    )
  }, [setAnalysis])

  const setPhoto = useCallback((kind: PhotoKind, file: File | null, result: PhotoCheckResult | null) => {
    setFiles((prev) => {
      const next = { ...prev }
      if (file) next[kind] = file
      else delete next[kind]
      return next
    })
    setChecks((prev) => ({ ...prev, [kind]: result }))
  }, [])

  const setRadiatorVideo = useCallback((file: File | null, result: RadiatorVideoResult | null) => {
    setRadiatorVideoFile(file)
    setRadiatorVideoResult(result)
  }, [])

  const setQuotes = useCallback((q: CheckedQuote[]) => {
    setQuotesState(q)
  }, [])

  const setConflictDecision = useCallback((key: string, decision: ConflictDecision | null) => {
    setConflictDecisions((prev) => {
      const next = { ...prev }
      if (decision) next[key] = decision
      else delete next[key]
      return next
    })
  }, [])

  const startReview = useCallback(() => {
    if (!analysis) return
    const run = ++reviewRun.current
    const startedAt = Date.now()
    setConflictDecisions({})
    setReview({ status: 'running', startedAt })
    const reviewQuotes: ReviewQuote[] = quotes.map((q, i) => ({
      quote_id: quoteId(i, q.result),
      pages: q.group.pages,
      reading: q.result?.verified.reading ?? null,
    }))
    api
      .reviewAnalysis(analysis, files, reviewQuotes)
      .then((result) => {
        if (run === reviewRun.current)
          setReview({ status: 'done', result, elapsedMs: Date.now() - startedAt, quoteCount: reviewQuotes.length })
      })
      .catch((e: unknown) => {
        if (run === reviewRun.current)
          setReview({ status: 'failed', message: e instanceof Error ? e.message : 'Review failed' })
      })
  }, [analysis, files, quotes])

  const photos = useMemo(
    () =>
      PHOTO_SLOTS.map((s) => ({
        ...s,
        result: checks[s.kind] ?? null,
        fileName: files[s.kind]?.name ?? null,
      })),
    [checks, files],
  )

  const district = address ? outwardCode(address.postcode) : analysis?.postcode_district
  const placeLabel = district ? `house in ${district}` : null

  const value = useMemo(
    () => ({
      address,
      setAddress,
      placeLabel,
      photos,
      files,
      setPhoto,
      radiatorVideo,
      radiatorVideoResult,
      setRadiatorVideo,
      analysis,
      setAnalysis,
      quotes,
      setQuotes,
      review,
      startReview,
      conflictDecisions,
      setConflictDecision,
      samSampleLoaded,
      loadSamSample,
    }),
    [
      address,
      setAddress,
      placeLabel,
      photos,
      files,
      setPhoto,
      radiatorVideo,
      radiatorVideoResult,
      setRadiatorVideo,
      analysis,
      setAnalysis,
      quotes,
      setQuotes,
      review,
      startReview,
      conflictDecisions,
      setConflictDecision,
      samSampleLoaded,
      loadSamSample,
    ],
  )

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
}

export function useSession() {
  const ctx = useContext(SessionContext)
  if (!ctx) throw new Error('useSession outside provider')
  return ctx
}
