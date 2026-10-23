import {
  SAM_ANALYSIS,
  SAM_EPC_ADDRESSES,
  SAM_QUOTE_CHECKS,
  mockPhotoCheck,
  mockVerificationStream,
} from './samMocks'
import type {
  AnalysisBundle,
  EpcAddress,
  PhotoCheckResult,
  PhotoKind,
  QuoteCheckResult,
  VerificationLogEntry,
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
  if (!res.ok) throw new Error(`EPC search failed: ${res.status}`)
  return res.json() as Promise<EpcAddress[]>
}

export async function checkPhoto(kind: PhotoKind, _file: File): Promise<PhotoCheckResult> {
  if (isMockMode()) {
    await mockDelay(600, 1400)
    const blurry = _file.name.toLowerCase().includes('blur')
    return mockPhotoCheck(kind, blurry)
  }
  const form = new FormData()
  form.append('kind', kind)
  form.append('file', _file)
  const res = await fetch('/api/photos/check', { method: 'POST', body: form })
  if (!res.ok) throw new Error(`Photo check failed: ${res.status}`)
  return res.json() as Promise<PhotoCheckResult>
}

export async function streamVerificationLog(): Promise<VerificationLogEntry[]> {
  if (isMockMode()) {
    await mockDelay(200, 400)
    return mockVerificationStream()
  }
  const res = await fetch('/api/verification/log')
  if (!res.ok) throw new Error(`Verification log failed: ${res.status}`)
  return res.json() as Promise<VerificationLogEntry[]>
}

export async function fetchAnalysis(_lmkKey: string): Promise<AnalysisBundle> {
  if (isMockMode()) {
    await mockDelay(800, 1200)
    return SAM_ANALYSIS
  }
  const res = await fetch(`/api/analysis/${encodeURIComponent(_lmkKey)}`)
  if (!res.ok) throw new Error(`Analysis failed: ${res.status}`)
  return res.json() as Promise<AnalysisBundle>
}

export async function checkQuotes(files: File[]): Promise<QuoteCheckResult[]> {
  if (isMockMode()) {
    await mockDelay(1000, 1800)
    return files.map((f, i) => {
      const base = SAM_QUOTE_CHECKS[i % SAM_QUOTE_CHECKS.length]
      return { ...base, filename: f.name || base.filename }
    })
  }
  const form = new FormData()
  for (const file of files) form.append('quotes', file)
  const res = await fetch('/api/quotes/check', { method: 'POST', body: form })
  if (!res.ok) throw new Error(`Quote check failed: ${res.status}`)
  return res.json() as Promise<QuoteCheckResult[]>
}

export const api = {
  searchEpcAddresses,
  checkPhoto,
  streamVerificationLog,
  fetchAnalysis,
  checkQuotes,
}
