import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { FlowProvider } from '../context/FlowContext'
import { SessionProvider } from '../context/SessionContext'
import { FlowNav } from './FlowNav'
import { FlowStepGate } from './FlowStepGate'
import { StartScreen } from '../screens/StartScreen'

vi.mock('../api/client', () => ({
  api: {
    searchEpcAddresses: vi.fn().mockResolvedValue([]),
  },
  isMockMode: () => true,
}))

describe('FlowNav sample mode', () => {
  afterEach(() => cleanup())

  it('unlocks every step after loading the Sam sample', async () => {
    const user = userEvent.setup()
    render(
      <SessionProvider>
        <MemoryRouter initialEntries={['/']}>
          <FlowProvider>
            <FlowStepGate>
              <FlowNav />
              <Routes>
                <Route path="/" element={<StartScreen />} />
              </Routes>
            </FlowStepGate>
          </FlowProvider>
        </MemoryRouter>
      </SessionProvider>,
    )
    await user.click(screen.getByRole('button', { name: /Load Sam's sample/i }))
    const nav = screen.getByRole('navigation', { name: 'Guided flow' })
    expect(within(nav).getByRole('link', { name: 'Pack' })).toBeInTheDocument()
  })
})
