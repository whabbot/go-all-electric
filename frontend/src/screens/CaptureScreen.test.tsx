import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { SessionProvider } from '../context/SessionContext'
import { CAPTURE_STATUS_LABEL, CAPTURE_SUMMARY_ITEMS } from '../lib/captureGuide'
import { WHY_NEED } from '../lib/captureWhyNeed'
import { CaptureScreen } from './CaptureScreen'

vi.mock('../api/client', () => ({
  api: {
    checkPhoto: vi.fn(),
    checkRadiatorVideo: vi.fn(),
  },
  isMockMode: () => true,
}))

function renderCapture() {
  return render(
    <SessionProvider>
      <MemoryRouter>
        <CaptureScreen />
      </MemoryRouter>
    </SessionProvider>,
  )
}

describe('CaptureScreen guide', () => {
  afterEach(() => {
    cleanup()
  })

  it('lists each capture input with required, optional, or recommended status', () => {
    renderCapture()
    const list = document.querySelector('.capture-guide-list')
    if (!list) throw new Error('capture guide list missing')
    const items = list.querySelectorAll('li')
    expect(items).toHaveLength(CAPTURE_SUMMARY_ITEMS.length)
    CAPTURE_SUMMARY_ITEMS.forEach((item, index) => {
      const row = items[index]
      expect(row.querySelector('.capture-guide-label')?.textContent).toBe(item.label)
      expect(row.querySelector(`.capture-guide-status--${item.status}`)?.textContent).toBe(
        CAPTURE_STATUS_LABEL[item.status],
      )
    })
  })

  it('shows a why-need control for each capture upload and the radiator video', () => {
    renderCapture()
    const triggers = screen.getAllByRole('button', { name: 'Why do we need this?' })
    // Five photo slots plus the radiator walkthrough option.
    expect(triggers).toHaveLength(6)
  })

  it('opens the why-need dialog with matching copy, closes on Escape, and restores focus', async () => {
    const user = userEvent.setup()
    renderCapture()
    const trigger = screen.getAllByRole('button', { name: 'Why do we need this?' })[0]
    trigger.focus()
    expect(trigger).toHaveFocus()

    await user.click(trigger)
    const content = WHY_NEED.boiler_plate
    const dialog = screen.getByRole('dialog', { name: content.dialogTitle })
    expect(dialog).toBeInTheDocument()
    expect(screen.getByText(content.bullets[0])).toBeInTheDocument()
    const closeBtn = screen.getByRole('button', { name: 'Close' })
    await waitFor(() => expect(closeBtn).toHaveFocus())

    await user.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(trigger).toHaveFocus()
  })

  it('opens the examples dialog, traps focus, closes on Escape, and restores focus', async () => {
    const user = userEvent.setup()
    renderCapture()
    const trigger = screen.getAllByRole('button', { name: 'See examples' })[0]
    trigger.focus()
    expect(trigger).toHaveFocus()

    await user.click(trigger)
    const dialog = screen.getByRole('dialog', { name: /Example photos:/ })
    expect(dialog).toBeInTheDocument()
    const closeBtn = screen.getByRole('button', { name: 'Close' })
    await waitFor(() => expect(closeBtn).toHaveFocus())

    await user.keyboard('{Tab}')
    expect(dialog.contains(document.activeElement)).toBe(true)

    await user.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(trigger).toHaveFocus()
  })
})
