import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { SessionProvider } from '../context/SessionContext'
import { WHY_NEED } from '../lib/captureWhyNeed'
import { QuotesScreen } from './QuotesScreen'

vi.mock('../api/client', () => ({
  api: {
    checkQuotes: vi.fn(),
  },
  isMockMode: () => true,
}))

vi.mock('../lib/pdfToImages', () => ({
  pdfFileToPageImages: vi.fn(),
}))

function renderQuotes() {
  return render(
    <SessionProvider>
      <MemoryRouter>
        <QuotesScreen />
      </MemoryRouter>
    </SessionProvider>,
  )
}

describe('QuotesScreen why-need', () => {
  afterEach(() => {
    cleanup()
  })

  it('shows why-need for installer quotes and closes on Escape with focus restored', async () => {
    const user = userEvent.setup()
    renderQuotes()
    const trigger = screen.getByRole('button', { name: 'Why do we need this?' })
    trigger.focus()
    await user.click(trigger)

    const content = WHY_NEED.installer_quotes
    expect(screen.getByRole('dialog', { name: content.dialogTitle })).toBeInTheDocument()
    expect(screen.getByText(content.bullets[0])).toBeInTheDocument()

    await user.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(trigger).toHaveFocus()
  })
})
