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

  it('lists each capture slot in checklist order with status chips', () => {
    renderCapture()
    const list = document.querySelector('.capture-slot-list')
    if (!list) throw new Error('capture slot list missing')
    const items = list.querySelectorAll(':scope > li')
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

  it('opens gas bill by default and exposes accessible disclosure controls', () => {
    renderCapture()
    const disclosures = screen.getAllByRole('button', { name: /Gas bill/i })
    const toggle = disclosures.find((el) => el.classList.contains('capture-slot-disclosure'))
    expect(toggle).toBeDefined()
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    expect(toggle).toHaveAttribute('aria-controls')
  })

  it('shows a why-need control for each capture upload and the radiator video when expanded', async () => {
    const user = userEvent.setup()
    renderCapture()
    // Gas bill panel is open by default.
    expect(screen.getAllByRole('button', { name: 'Why do we need this?' })).toHaveLength(1)

    const radiatorsToggle = screen
      .getAllByRole('button', { name: /Radiators/i })
      .find((el) => el.classList.contains('capture-slot-disclosure'))
    if (!radiatorsToggle) throw new Error('radiators disclosure missing')
    await user.click(radiatorsToggle)

    const triggers = screen.getAllByRole('button', { name: 'Why do we need this?' })
    // Radiators photo plus the radiator walkthrough option.
    expect(triggers).toHaveLength(2)
  })

  it('includes the optional Loft slot after Gas bill in the checklist, with guidance, example photos, and why-need dialog', async () => {
    const user = userEvent.setup()
    renderCapture()

    expect(CAPTURE_SUMMARY_ITEMS[0].id).toBe('gas_bill')
    expect(CAPTURE_SUMMARY_ITEMS[1]).toMatchObject({
      id: 'loft',
      label: 'Loft',
      status: 'recommended',
    })

    const loftToggle = screen
      .getAllByRole('button', { name: /Loft/i })
      .find((el) => el.classList.contains('capture-slot-disclosure'))
    if (!loftToggle) throw new Error('loft disclosure missing')
    await user.click(loftToggle)

    expect(screen.getByRole('heading', { name: 'Loft (optional)' })).toBeInTheDocument()
    expect(screen.getByText(CAPTURE_GUIDANCE.loft.oneLine)).toBeInTheDocument()

    const examplesTriggers = screen.getAllByRole('button', { name: 'See examples' })
    expect(examplesTriggers).toHaveLength(1)
    await user.click(examplesTriggers[0])
    const examplesDialog = screen.getByRole('dialog', { name: 'Example photos: Loft (optional)' })
    expect(examplesDialog).toBeInTheDocument()
    expect(examplesDialog.querySelectorAll('img')).toHaveLength(2)
    expect(screen.getByText(CAPTURE_GUIDANCE.loft.goodReason, { exact: false })).toBeInTheDocument()
    expect(screen.getByText(CAPTURE_GUIDANCE.loft.badReason, { exact: false })).toBeInTheDocument()
    await user.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())

    const whyTriggers = screen.getAllByRole('button', { name: 'Why do we need this?' })
    await user.click(whyTriggers[0])
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
    const content = WHY_NEED.gas_bill
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
    expect(document.querySelectorAll('.capture-example-photo')).toHaveLength(0)
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
