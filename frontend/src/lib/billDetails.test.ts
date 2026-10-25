import { describe, expect, it } from 'vitest'
import { billIssue, billValues, parseBillDetails } from './billDetails'

describe('bill details', () => {
  it('accepts a leap year and preserves inclusive dates', () => {
    const result = parseBillDetails([{ kwh: '12000', start: '2024-01-01', end: '2024-12-31' }])
    expect(result.error).toBeNull()
    expect(billValues(result.known!).total_kwh).toBe(12000)
    expect(billValues(result.known!).monthly).toEqual([])
  })
  it('identifies partial years, gaps, overlaps and invalid dates', () => {
    const row = { kwh: '6000', start: '2025-01-01', end: '2025-06-30' }
    expect(billIssue(parseBillDetails([row]).known!.periods)).toContain('12 months in a row')
    expect(billIssue(parseBillDetails([row, { ...row, start: '2025-06-30', end: '2025-12-31' }]).known!.periods)).toContain('overlap')
    expect(billIssue(parseBillDetails([row, { ...row, start: '2025-08-01', end: '2025-12-31' }]).known!.periods)).toContain('gaps are OK')
    expect(parseBillDetails([{ ...row, start: '2025-02-30' }]).known).toBeNull()
  })
  it('converts twelve whole calendar months in order', () => {
    const rows = Array.from({ length: 12 }, (_, i) => ({ kwh: '1000', start: `2025-${String(i + 1).padStart(2, '0')}-01`, end: new Date(Date.UTC(2025, i + 1, 0)).toISOString().slice(0, 10) })).reverse()
    const parsed = parseBillDetails(rows)
    expect(parsed.error).toBeNull()
    const values = billValues(parsed.known!)
    expect(values.monthly).toHaveLength(12)
    expect(values.period_start).toBe('2025-01-01')
    expect(values.total_kwh).toBe(12000)
  })
})

it('invalidates results when any bill detail changes', async () => {
  const { analysisInputsFingerprint } = await import('./analysisInputs')
  const base = { certificateId: 'sample', files: {}, radiatorUploads: [], radiatorLabels: [], radiators: [], boilerDetails: {}, fuseDetails: {}, radiatorVideo: null }
  const billPeriods = [{ kwh: '12000', start: '2025-01-01', end: '2025-12-31' }]
  const before = analysisInputsFingerprint({ ...base, billPeriods })
  expect(analysisInputsFingerprint({ ...base, billPeriods: [{ ...billPeriods[0], kwh: '14000' }] })).not.toBe(before)
})

it('marks a result stale when house type or floor area changes', async () => {
  const { analysisInputsFingerprint } = await import('./analysisInputs')
  const base = { certificateId: 'sample', files: {}, radiatorUploads: [], radiatorLabels: [], radiators: [], boilerDetails: {}, fuseDetails: {}, radiatorVideo: null }
  const key = analysisInputsFingerprint(base)
  expect(analysisInputsFingerprint({ ...base, houseDetails: { house_type: 'detached' } })).not.toBe(key)
  expect(analysisInputsFingerprint({ ...base, houseDetails: { floor_area_m2: 90 } })).not.toBe(key)
})
