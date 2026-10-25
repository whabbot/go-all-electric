import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'
import { EstimateHero } from './EstimateHero'
import { mockAnalysisResult } from '../api/samMocks'

it('renders B-only sizing with the A reason and fix, without a comparison or ranked reasons', () => {
  const result = mockAnalysisResult(['gas_bill'])
  render(<EstimateHero analysis={{ ...result.bundle, fabric: null, cross_check: null }} billGap={null} epcGap={{ input: 'epc', message: 'Floor area is missing.', provide: 'Enter floor area on Start.' }} quoteKw={[]} />)
  expect(screen.getByText('Floor area is missing.')).toBeInTheDocument()
  expect(screen.getByText('Enter floor area on Start.')).toBeInTheDocument()
  expect(screen.getByText(/sizing uses your measured gas usage/)).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'Estimate B — measured' })).toBeInTheDocument()
  expect(screen.queryByText(/Why they disagree/)).not.toBeInTheDocument()
  expect(screen.queryByText(/Fabric ÷ measured/)).not.toBeInTheDocument()
})
