import type { AnalysisResult, EpcAddress } from '../api'

/** Flow-related session fields used by flow.ts (keeps flow logic testable without React). */
export type Session = {
  address: EpcAddress | null
  analysis: AnalysisResult | null
  samSampleLoaded: boolean
}
