import { describe, expect, it } from 'vitest'
import { formatGBPRange, formatSignedMoneyRange } from './format'

describe('formatGBPRange', () => {
  it('formats mixed savings and extra cost readably', () => {
    expect(formatGBPRange(-120, -42, 35, '/yr')).toBe(
      'about £42 more/yr (range £120 more to £35 saving)',
    )
  })

  it('formats all-negative deltas', () => {
    expect(formatSignedMoneyRange(-433, -179, -12, ' per year')).toBe(
      'about £179 more per year (range £433 more to £12 more)',
    )
  })
})
