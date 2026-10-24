import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AccessGate } from './AccessGate'

vi.mock('../api/client', () => ({
  isMockMode: () => false,
}))

describe('AccessGate access code visibility', () => {
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  beforeEach(() => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: false, status: 401 }),
    )
  })

  async function waitForAccessForm() {
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Show access code' })).toBeInTheDocument()
    })
  }

  it('keeps the code hidden by default', async () => {
    render(<AccessGate><div>inside</div></AccessGate>)
    await waitForAccessForm()
    expect(screen.getByLabelText('Enter access code')).toHaveAttribute('type', 'password')
  })

  it('reveals then hides the code when toggled', async () => {
    const user = userEvent.setup()
    render(<AccessGate><div>inside</div></AccessGate>)
    await waitForAccessForm()
    const input = screen.getByLabelText('Enter access code')

    await user.click(screen.getByRole('button', { name: 'Show access code' }))
    expect(input).toHaveAttribute('type', 'text')
    expect(screen.getByRole('button', { name: 'Hide access code' })).toHaveAttribute('aria-pressed', 'true')

    await user.click(screen.getByRole('button', { name: 'Hide access code' }))
    expect(input).toHaveAttribute('type', 'password')
  })

  it('does not submit the form when toggling visibility', async () => {
    const user = userEvent.setup()
    const fetchMock = vi.mocked(fetch)
    render(<AccessGate><div>inside</div></AccessGate>)
    await waitForAccessForm()
    expect(fetchMock).toHaveBeenCalledTimes(1)

    await user.click(screen.getByRole('button', { name: 'Show access code' }))
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock).not.toHaveBeenCalledWith('/api/session', expect.anything())
  })
})
