import { describe, expect, it } from 'vitest'
import { mockAnalysisResult } from '../api/samMocks'
import { canReachNextStep, furthestReachableIndex } from './flow'
import type { Session } from '../context/flowSession'

const sampleSession: Session = {
  address: {
    certificate_id: 'x',
    address: 'a',
    postcode: 'N10 2AB',
    registration_date: '2020-01-01',
    current_energy_efficiency_band: 'D',
  },
  analysis: mockAnalysisResult(['gas_bill'], false),
  samSampleLoaded: true,
}

describe('flow forward navigation', () => {
  it('allows Next on quotes when sample unlocked steps without visiting cost/spec', () => {
    const visited = new Set(['/', '/capture', '/estimates', '/quotes'])
    expect(furthestReachableIndex(sampleSession, visited)).toBe(7)
    expect(canReachNextStep('/quotes', sampleSession, visited)).toBe(true)
  })
})
