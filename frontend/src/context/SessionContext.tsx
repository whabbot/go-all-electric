import { createContext, useContext, useMemo, useState, type ReactNode } from 'react'
import type { AnalysisBundle, EpcAddress, PhotoCheckResult, PhotoKind } from '../api'

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
  { kind: 'outdoor_space', label: 'Outdoor unit spot' },
  { kind: 'gas_bill', label: 'Gas bill' },
]

type Session = {
  address: EpcAddress | null
  setAddress: (a: EpcAddress | null) => void
  photos: PhotoSlot[]
  setPhotoResult: (kind: PhotoKind, result: PhotoCheckResult | null, fileName: string | null) => void
  analysis: AnalysisBundle | null
  setAnalysis: (a: AnalysisBundle | null) => void
}

const SessionContext = createContext<Session | null>(null)

export function SessionProvider({ children }: { children: ReactNode }) {
  const [address, setAddress] = useState<EpcAddress | null>(null)
  const [analysis, setAnalysisState] = useState<AnalysisBundle | null>(() => {
    try {
      const raw = sessionStorage.getItem('gae-analysis')
      return raw ? (JSON.parse(raw) as AnalysisBundle) : null
    } catch {
      return null
    }
  })

  const setAnalysis = (a: AnalysisBundle | null) => {
    setAnalysisState(a)
    try {
      if (a) sessionStorage.setItem('gae-analysis', JSON.stringify(a))
      else sessionStorage.removeItem('gae-analysis')
    } catch {
      /* private mode / storage full */
    }
  }
  const [photoState, setPhotoState] = useState<Record<PhotoKind, { result: PhotoCheckResult | null; fileName: string | null }>>(
    () =>
      Object.fromEntries(
        PHOTO_SLOTS.map((s) => [s.kind, { result: null, fileName: null }]),
      ) as Record<PhotoKind, { result: PhotoCheckResult | null; fileName: string | null }>,
  )

  const setPhotoResult = (kind: PhotoKind, result: PhotoCheckResult | null, fileName: string | null) => {
    setPhotoState((prev) => ({ ...prev, [kind]: { result, fileName } }))
  }

  const photos = useMemo(
    () =>
      PHOTO_SLOTS.map((s) => ({
        ...s,
        result: photoState[s.kind].result,
        fileName: photoState[s.kind].fileName,
      })),
    [photoState],
  )

  const value = useMemo(
    () => ({
      address,
      setAddress,
      photos,
      setPhotoResult,
      analysis,
      setAnalysis,
    }),
    [address, photos, analysis],
  )

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
}

export function useSession() {
  const ctx = useContext(SessionContext)
  if (!ctx) throw new Error('useSession outside provider')
  return ctx
}
