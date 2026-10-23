import type { QuoteCheckResult } from '../api'

/** Outward code of a UK postcode ("N10 2AB" -> "N10"): the only location the UI shows. */
export function outwardCode(postcode: string): string {
  const compact = postcode.replace(/\s+/g, '').toUpperCase()
  return compact.length > 3 ? compact.slice(0, -3) : compact
}

/** Quote labels never use the file name, which can carry a name or address. */
export function quoteId(index: number, result: QuoteCheckResult | null): string {
  const letter = String.fromCharCode(65 + index)
  return result?.quoted_kw != null ? `Quote ${letter} (${result.quoted_kw} kW)` : `Quote ${letter}`
}
