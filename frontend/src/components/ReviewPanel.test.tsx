import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useEffect } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, type ReviewResult } from '../api'
import { mockAnalysisResult, mockReview } from '../api/samMocks'
import { SessionProvider, useSession } from '../context/SessionContext'
import { ReviewPanel } from './ReviewPanel'

function SeededReviewPanel() {
  const { analysis, setAnalysis } = useSession()
  useEffect(() => {
    if (!analysis) {
      setAnalysis(mockAnalysisResult(['boiler_plate', 'radiators', 'gas_bill']))
    }
  }, [analysis, setAnalysis])
  return <ReviewPanel />
}

describe('ReviewPanel tested conflict proposals', () => {
  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
  })

  it('renders a tested EPC conflict proposal with evidence, code re-run result, and session-only confirm/dismiss controls', async () => {
    const user = userEvent.setup()
    const reviewSpy = vi
      .spyOn(api, 'reviewAnalysis')
      .mockResolvedValue(mockReview([]))

    render(
      <SessionProvider>
        <SeededReviewPanel />
      </SessionProvider>,
    )

    const startBtn = await screen.findByRole('button', { name: 'Ask Gemini to review everything' })
    await user.click(startBtn)

    expect(await screen.findByRole('heading', { name: 'What if the EPC is wrong here?' })).toBeInTheDocument()
    expect(
      screen.getByText('Wall insulation: unfilled cavity walls → filled cavity walls'),
    ).toBeInTheDocument()
    expect(screen.getByText('Evidence: Gas bill')).toBeInTheDocument()
    expect(
      screen.getByText(/The EPC records unfilled cavity walls \(assumed\)/),
    ).toBeInTheDocument()
    expect(screen.getByText('8.8 kW → 7.1 kW')).toBeInTheDocument()
    expect(screen.getByText('A-vs-B gap shrinks (4.0 → 2.4 kW)')).toBeInTheDocument()

    expect(
      screen.getByText('Loft insulation depth: 100 mm loft insulation → 270 mm+ loft insulation'),
    ).toBeInTheDocument()
    expect(screen.getByText('Evidence: Loft photo')).toBeInTheDocument()
    expect(screen.getByText('8.8 kW → 8.5 kW')).toBeInTheDocument()
    expect(screen.getByText('A-vs-B gap shrinks (4.0 → 3.8 kW)')).toBeInTheDocument()

    const [confirmBtn] = screen.getAllByRole('button', { name: 'Confirm' })
    const [dismissBtn] = screen.getAllByRole('button', { name: 'Dismiss' })
    expect(confirmBtn).toHaveAttribute('aria-pressed', 'false')
    expect(dismissBtn).toHaveAttribute('aria-pressed', 'false')

    await user.click(confirmBtn)
    expect(screen.getByRole('button', { name: 'Confirmed' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByText('Confirmed for this session only.')).toBeInTheDocument()

    await user.click(dismissBtn)
    expect(screen.getByRole('button', { name: 'Dismissed' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByText('Dismissed for this session only.')).toBeInTheDocument()

    // Confirm/dismiss is held in session state only; no extra API call is made.
    expect(reviewSpy).toHaveBeenCalledTimes(1)
  })

  it('shows the no-conflict note when Argon reports no_conflict_found', async () => {
    const user = userEvent.setup()
    const base = mockReview([])
    const noConflictResult: ReviewResult = {
      ...base,
      review: {
        ...base.review,
        conflict_status: 'no_conflict_found',
        input_conflicts: [],
      },
      tested_conflicts: [],
    }
    vi.spyOn(api, 'reviewAnalysis').mockResolvedValue(noConflictResult)

    render(
      <SessionProvider>
        <SeededReviewPanel />
      </SessionProvider>,
    )

    const startBtn = await screen.findByRole('button', { name: 'Ask Gemini to review everything' })
    await user.click(startBtn)

    expect(
      await screen.findByText('No EPC input conflicts found across your photos and readings.'),
    ).toBeInTheDocument()
  })
})
