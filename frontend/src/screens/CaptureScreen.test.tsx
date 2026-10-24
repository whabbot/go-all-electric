import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { SessionProvider } from '../context/SessionContext'
import { CAPTURE_GUIDANCE, CAPTURE_STATUS_LABEL, CAPTURE_SUMMARY_ITEMS } from '../lib/captureGuide'
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

  it('lists each capture input with most important, optional, or recommended status', () => {
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
      if (item.reason) {
        expect(row.querySelector('.capture-guide-reason')?.textContent).toBe(item.reason)
      }
    })
  })

  it('shows a why-need control for each capture upload and the radiator video', () => {
    renderCapture()
    const triggers = screen.getAllByRole('button', { name: 'Why do we need this?' })
    // Six photo slots plus the radiator walkthrough option.
    expect(triggers).toHaveLength(7)
  })

  it('includes the optional Loft slot after Gas bill in the checklist, with guidance, examples SVG, and why-need dialog', async () => {
    const user = userEvent.setup()
    renderCapture()

    expect(CAPTURE_SUMMARY_ITEMS[0].id).toBe('gas_bill')
    expect(CAPTURE_SUMMARY_ITEMS[1]).toMatchObject({
      id: 'loft',
      label: 'Loft',
      status: 'recommended',
    })

    expect(screen.getByRole('heading', { name: 'Loft (optional)' })).toBeInTheDocument()
    expect(screen.getByText(CAPTURE_GUIDANCE.loft.oneLine)).toBeInTheDocument()

    // Loft is the 6th photo slot (index 5 in "See examples", index 6 in "Why do we need this?" after radiator video).
    const examplesTriggers = screen.getAllByRole('button', { name: 'See examples' })
    await user.click(examplesTriggers[5])
    const examplesDialog = screen.getByRole('dialog', { name: 'Example photos: Loft (optional)' })
    expect(examplesDialog).toBeInTheDocument()
    expect(examplesDialog.querySelectorAll('svg')).toHaveLength(2)
    expect(screen.getByText(CAPTURE_GUIDANCE.loft.goodReason, { exact: false })).toBeInTheDocument()
    expect(screen.getByText(CAPTURE_GUIDANCE.loft.badReason, { exact: false })).toBeInTheDocument()
    await user.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())

    const whyTriggers = screen.getAllByRole('button', { name: 'Why do we need this?' })
    await user.click(whyTriggers[6])
    const whyDialog = screen.getByRole('dialog', { name: WHY_NEED.loft.dialogTitle })
    expect(whyDialog).toBeInTheDocument()
    expect(screen.getByText(WHY_NEED.loft.bullets[1])).toBeInTheDocument()
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
