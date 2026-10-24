import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { mockAnalysisResult, SAM_EPC_ADDRESSES } from '../api/samMocks'
import {
  api,
  type AnalysisResult,
  type EpcAddress,
  type KnownBoiler,
  type KnownFuse,
  type PhotoCheckResult,
  type PhotoKind,
  type QuoteCheckResult,
  type QuoteUploadGroup,
  type RadiatorUpload,
  type RadiatorVideoResult,
  type ReviewQuote,
  type ReviewResult,
} from '../api'
import {
  hasEntries,
  parseKnownBoiler,
  parseKnownFuse,
  parseKnownRadiator,
  radiatorLabel,
  type DetailInputs,
} from '../lib/knownDetails'
import { outwardCode, quoteId } from '../lib/labels'

export const MAX_RADIATORS = 8
export const MAX_PHOTOS_PER_RADIATOR = 3

export type RadiatorPhotoItem = {
  id: string
  file: File
  fileName: string
  previewUrl: string
  result: PhotoCheckResult | null
  checking: boolean
  error: string | null
}

/** One radiator: any number of photos of it (read as one radiator), a label and known details. */
export type RadiatorCard = {
  id: string
  /** From the room pick list; '' when not picked. Display only: never sent anywhere. */
  room: string
  /** Short optional free text, e.g. "under the window". Display only: never sent anywhere. */
  note: string
  photos: RadiatorPhotoItem[]
  details: DetailInputs
}

type RadiatorPhotoPatch = Partial<
  Pick<RadiatorPhotoItem, 'file' | 'fileName' | 'previewUrl' | 'result' | 'checking' | 'error'>
>

type PhotoSlot = {
  kind: PhotoKind
  label: string
  result: PhotoCheckResult | null
  fileName: string | null
  /** Details were entered by hand, so the slot counts even without a photo. */
  entered: boolean
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
  radiators: RadiatorCard[]
  addRadiator: () => string
  updateRadiator: (id: string, patch: Partial<Pick<RadiatorCard, 'room' | 'note' | 'details'>>) => void
  removeRadiator: (id: string) => void
  addRadiatorPhoto: (radiatorId: string, file: File) => string
  updateRadiatorPhoto: (radiatorId: string, photoId: string, patch: RadiatorPhotoPatch) => void
  removeRadiatorPhoto: (radiatorId: string, photoId: string) => void
  /** Radiators that count (a photo or a detail), numbered in this order for the analysis. */
  radiatorUploads: RadiatorUpload[]
  /** Display labels aligned with `radiatorUploads`; they never leave this tab. */
  radiatorLabels: (string | null)[]
  boilerDetails: DetailInputs
  setBoilerDetails: (d: DetailInputs) => void
  fuseDetails: DetailInputs
  setFuseDetails: (d: DetailInputs) => void
  knownBoiler: KnownBoiler | null
  knownFuse: KnownFuse | null
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

function aggregateRadiatorResult(items: RadiatorPhotoItem[], radiatorCount: number): PhotoCheckResult | null {
  if (items.length === 0 || items.some((i) => i.checking)) return null
  const withWarn = items.find((i) => i.result && !i.result.legible)
  if (withWarn?.result) return withWarn.result
  const withError = items.find((i) => i.error)
  if (withError) {
    return {
      kind: 'radiators',
      expected_kind: 'radiators',
      legible: false,
      usable: false,
      matches_expected: true,
      summary: withError.error ?? 'Could not check radiator photo.',
      key_fields: {},
      confidence: 'low',
      retake_hint: null,
      privacy_warning: null,
      model: 'client',
      elapsed_ms: 0,
    }
  }
  const lastResult = items[items.length - 1]?.result ?? null
  if (!lastResult) return null
  if (items.length === 1 && radiatorCount === 1) return lastResult
  return {
    ...lastResult,
    summary: `${radiatorCount} radiator${radiatorCount === 1 ? '' : 's'} ready`,
  }
}

function counts(card: RadiatorCard): boolean {
  return card.photos.length > 0 || hasEntries(parseKnownRadiator(card.details).known)
}

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
  const [radiators, setRadiators] = useState<RadiatorCard[]>([])
  const [boilerDetails, setBoilerDetails] = useState<DetailInputs>({})
  const [fuseDetails, setFuseDetails] = useState<DetailInputs>({})
  const radiatorIdCounter = useRef(0)
  const radiatorsRef = useRef<RadiatorCard[]>([])
  radiatorsRef.current = radiators
  const [radiatorVideo, setRadiatorVideoFile] = useState<File | null>(null)
  const [radiatorVideoResult, setRadiatorVideoResult] = useState<RadiatorVideoResult | null>(null)
  const [quotes, setQuotesState] = useState<CheckedQuote[]>([])
  const [review, setReview] = useState<ReviewState>({ status: 'idle' })
  const [conflictDecisions, setConflictDecisions] = useState<Record<string, ConflictDecision>>({})
  const [samSampleLoaded, setSamSampleLoaded] = useState(false)
  const reviewRun = useRef(0)

  useEffect(() => {
    return () => {
      for (const card of radiatorsRef.current) {
        for (const item of card.photos) URL.revokeObjectURL(item.previewUrl)
      }
    }
  }, [])

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

  const addRadiator = useCallback((): string => {
    const id = `radiator-${++radiatorIdCounter.current}`
    setRadiators((prev) =>
      prev.length >= MAX_RADIATORS ? prev : [...prev, { id, room: '', note: '', photos: [], details: {} }],
    )
    return id
  }, [])

  const updateRadiator = useCallback(
    (id: string, patch: Partial<Pick<RadiatorCard, 'room' | 'note' | 'details'>>) => {
      setRadiators((prev) => prev.map((card) => (card.id === id ? { ...card, ...patch } : card)))
    },
    [],
  )

  const removeRadiator = useCallback((id: string) => {
    setRadiators((prev) => {
      for (const item of prev.find((card) => card.id === id)?.photos ?? []) URL.revokeObjectURL(item.previewUrl)
      return prev.filter((card) => card.id !== id)
    })
  }, [])

  const addRadiatorPhoto = useCallback((radiatorId: string, file: File): string => {
    const id = `rad-photo-${++radiatorIdCounter.current}`
    const previewUrl = URL.createObjectURL(file)
    setRadiators((prev) =>
      prev.map((card) =>
        card.id === radiatorId
          ? {
              ...card,
              photos: [
                ...card.photos,
                { id, file, fileName: file.name, previewUrl, result: null, checking: true, error: null },
              ],
            }
          : card,
      ),
    )
    return id
  }, [])

  const updateRadiatorPhoto = useCallback((radiatorId: string, photoId: string, patch: RadiatorPhotoPatch) => {
    setRadiators((prev) =>
      prev.map((card) => {
        if (card.id !== radiatorId) return card
        return {
          ...card,
          photos: card.photos.map((item) => {
            if (item.id !== photoId) return item
            if (patch.previewUrl && patch.previewUrl !== item.previewUrl) URL.revokeObjectURL(item.previewUrl)
            return { ...item, ...patch }
          }),
        }
      }),
    )
  }, [])

  const removeRadiatorPhoto = useCallback((radiatorId: string, photoId: string) => {
    setRadiators((prev) =>
      prev.map((card) => {
        if (card.id !== radiatorId) return card
        const target = card.photos.find((item) => item.id === photoId)
        if (target) URL.revokeObjectURL(target.previewUrl)
        return { ...card, photos: card.photos.filter((item) => item.id !== photoId) }
      }),
    )
  }, [])

  const counted = useMemo(() => radiators.filter(counts), [radiators])
  const radiatorUploads = useMemo(
    (): RadiatorUpload[] =>
      counted.map((card) => ({ photos: card.photos.map((p) => p.file), known: parseKnownRadiator(card.details).known })),
    [counted],
  )
  const radiatorLabels = useMemo(() => counted.map((card) => radiatorLabel(card.room, card.note)), [counted])
  const knownBoiler = useMemo(() => {
    const { known } = parseKnownBoiler(boilerDetails)
    return hasEntries(known) ? known : null
  }, [boilerDetails])
  const knownFuse = useMemo(() => {
    const { known } = parseKnownFuse(fuseDetails)
    return hasEntries(known) ? known : null
  }, [fuseDetails])

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
      .reviewAnalysis(analysis, files, reviewQuotes, radiatorUploads)
      .then((result) => {
        if (run === reviewRun.current)
          setReview({ status: 'done', result, elapsedMs: Date.now() - startedAt, quoteCount: reviewQuotes.length })
      })
      .catch((e: unknown) => {
        if (run === reviewRun.current)
          setReview({ status: 'failed', message: e instanceof Error ? e.message : 'Review failed' })
      })
  }, [analysis, files, quotes, radiatorUploads])

  const photos = useMemo(
    () =>
      PHOTO_SLOTS.map((s): PhotoSlot => {
        if (s.kind === 'radiators') {
          const radiatorPhotos = counted.flatMap((card) => card.photos)
          return {
            ...s,
            result: aggregateRadiatorResult(radiatorPhotos, counted.length),
            fileName: radiatorPhotos.length > 0 ? `${counted.length} radiator${counted.length === 1 ? '' : 's'}` : null,
            entered: counted.length > 0 && radiatorPhotos.length === 0,
          }
        }
        return {
          ...s,
          result: checks[s.kind] ?? null,
          fileName: files[s.kind]?.name ?? null,
          entered: (s.kind === 'boiler_plate' && knownBoiler != null) || (s.kind === 'fuse_cutout' && knownFuse != null),
        }
      }),
    [checks, files, counted, knownBoiler, knownFuse],
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
      radiators,
      addRadiator,
      updateRadiator,
      removeRadiator,
      addRadiatorPhoto,
      updateRadiatorPhoto,
      removeRadiatorPhoto,
      radiatorUploads,
      radiatorLabels,
      boilerDetails,
      setBoilerDetails,
      fuseDetails,
      setFuseDetails,
      knownBoiler,
      knownFuse,
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
      radiators,
      addRadiator,
      updateRadiator,
      removeRadiator,
      addRadiatorPhoto,
      updateRadiatorPhoto,
      removeRadiatorPhoto,
      radiatorUploads,
      radiatorLabels,
      boilerDetails,
      fuseDetails,
      knownBoiler,
      knownFuse,
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
