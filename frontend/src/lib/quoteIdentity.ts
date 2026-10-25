/** New quote upload groups get a stable id for the rest of the session. */
export function newQuoteId(): string {
  return crypto.randomUUID()
}
