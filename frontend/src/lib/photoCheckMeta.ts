import { isMockMode, type PhotoCheckResult } from '../api'

/** Attribution line for a photo check — never presents offline demo data as a live model. */
export function photoCheckAttribution(result: PhotoCheckResult): string {
  const seconds = (result.elapsed_ms / 1000).toFixed(1)
  if (isMockMode()) {
    return `(offline sample, ${seconds}s)`
  }
  return `(${result.model}, ${seconds}s)`
}
