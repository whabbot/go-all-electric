import type { GasPeriod, KnownGasBill } from '../api'

export type BillPeriodInputs = { kwh: string; start: string; end: string }
export const emptyBillPeriod = (): BillPeriodInputs => ({ kwh: '', start: '', end: '' })
const day = 86400000
const iso = (d: Date) => d.toISOString().slice(0, 10)
const date = (v: string) => new Date(`${v}T00:00:00Z`)
const show = (v: string) => date(v).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })

export function selectBillPeriods(periods: GasPeriod[]) {
  const chosen: GasPeriod[] = []
  const notes: string[] = []
  for (const period of [...periods].sort((a, b) => (+date(b.end) - +date(b.start)) - (+date(a.end) - +date(a.start)))) {
    const overlap = chosen.find(p => p.start <= period.end && period.start <= p.end)
    if (overlap) notes.push(`Period ${show(period.start)}–${show(period.end)} overlaps a longer period: total counted once; contained usage helps show the distribution.`)
    else chosen.push(period)
  }
  return { chosen: chosen.sort((a, b) => a.start.localeCompare(b.start)), notes }
}

export function billIssue(periods: GasPeriod[]): string | null {
  const { chosen: rows, notes } = selectBillPeriods(periods)
  if (!rows.length) return null
  const start = date(rows[0].start)
  const anniversary = new Date(Date.UTC(start.getUTCFullYear() + 1, start.getUTCMonth(), start.getUTCDate()))
  if (start.getUTCMonth() === 1 && start.getUTCDate() === 29) anniversary.setUTCDate(0)
  const contiguous = rows.every((p, i) => i === 0 || +date(p.start) === +date(rows[i - 1].end) + day)
  const complete = contiguous && +date(rows[rows.length - 1].end) + day === +anniversary
  return [...notes, ...(!complete ? ['12 months in a row is best. We can use these periods if they include enough winter heating; gaps are OK. Annual Costs will be estimated.'] : [])].join(' ') || null
}

export function parseBillDetails(inputs: BillPeriodInputs[]): { known: KnownGasBill | null; error: string | null } {
  if (!inputs.length) return { known: null, error: null }
  const periods: GasPeriod[] = []
  for (const row of inputs) {
    if (!row.kwh.trim() || !Number.isFinite(Number(row.kwh)) || Number(row.kwh) <= 0 || Number(row.kwh) > 40000) return { known: null, error: 'Enter gas used in kWh, greater than 0 and no more than 40,000.' }
    if (![row.start, row.end].every(v => /^\d{4}-\d{2}-\d{2}$/.test(v) && Number.isFinite(+date(v)) && iso(date(v)) === v)) return { known: null, error: 'Enter a valid start and end date for every period.' }
    if (row.end < row.start) return { known: null, error: 'End date must be on or after start date.' }
    periods.push({ kwh: Number(row.kwh), start: row.start, end: row.end })
  }
  const issue = billIssue(periods)
  const total = periods.reduce((s, p) => s + p.kwh, 0)
  if (!issue && (total < 2000 || total > 40000)) return { known: null, error: 'Annual gas usage must be between 2,000 and 40,000 kWh.' }
  return { known: { periods }, error: null }
}

export function billValues(bill: KnownGasBill) {
  const { chosen: rows } = selectBillPeriods(bill.periods)
  const { chosen: months } = selectBillPeriods(bill.periods.filter(p => {
    const start = date(p.start)
    return start.getUTCDate() === 1 && p.end === iso(new Date(Date.UTC(start.getUTCFullYear(), start.getUTCMonth() + 1, 0)))
  }))
  const monthly = months.map(p => ({ month: p.start.slice(0, 7), kwh: p.kwh }))
  return { period_start: rows[0].start, period_end: rows[rows.length - 1].end, total_kwh: rows.reduce((s, p) => s + p.kwh, 0), monthly }
}
