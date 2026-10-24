import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { FlowProvider } from '../context/FlowContext'
import { SessionProvider, useSession } from '../context/SessionContext'
import { FlowNav } from './FlowNav'
import { FlowStepActions } from './FlowStepActions'
import { FlowStepGate } from './FlowStepGate'
import { StartScreen } from '../screens/StartScreen'
import { PackScreen } from '../screens/PackScreen'

vi.mock('../api/client', () => ({
  api: {
    searchEpcAddresses: vi.fn().mockResolvedValue([]),
  },
  isMockMode: () => false,
}))

function FlowShell({ initialPath = '/' }: { initialPath?: string }) {
  return (
    <SessionProvider>
      <MemoryRouter initialEntries={[initialPath]}>
        <FlowProvider>
          <FlowStepGate>
            <FlowNav brand={<span>Go All-Electric</span>} />
            <Routes>
              <Route path="/" element={<StartScreen />} />
              <Route path="/capture" element={<p>Capture step</p>} />
              <Route path="/pack" element={<PackScreen />} />
            </Routes>
          </FlowStepGate>
        </FlowProvider>
      </MemoryRouter>
    </SessionProvider>
  )
}

describe('FlowNav', () => {
  afterEach(() => cleanup())

  it('marks locked steps as not clickable links', () => {
    render(<FlowShell initialPath="/" />)
    const nav = screen.getByRole('navigation', { name: 'Guided flow' })
    expect(within(nav).queryByRole('link', { name: 'Pack' })).not.toBeInTheDocument()
    expect(within(nav).getByText('Pack')).toHaveAttribute('aria-disabled', 'true')
  })

  it('redirects a direct URL to a locked step onto the furthest reachable step', () => {
    render(<FlowShell initialPath="/pack" />)
    expect(screen.getByRole('heading', { name: /Sam's heat pump puzzle/i })).toBeInTheDocument()
  })

  it('keeps session inputs when navigating back', async () => {
    const user = userEvent.setup()
    function PickHouse() {
      const { setAddress } = useSession()
      return (
        <button
          type="button"
          onClick={() =>
            setAddress({
              certificate_id: 'test-cert',
              address: '1 Test Street',
              postcode: 'N10 2AB',
              registration_date: '2020-01-01',
              current_energy_efficiency_band: 'C',
            })
          }
        >
          Pick test house
        </button>
      )
    }

    render(
      <SessionProvider>
        <MemoryRouter initialEntries={['/']}>
          <FlowProvider>
            <PickHouse />
            <FlowStepGate>
              <FlowNav brand={<span>Go All-Electric</span>} />
              <Routes>
                <Route path="/" element={<StartScreen />} />
                <Route path="/capture" element={<p>Capture step</p>} />
              </Routes>
              <FlowStepActions />
            </FlowStepGate>
          </FlowProvider>
        </MemoryRouter>
      </SessionProvider>,
    )

    await user.click(screen.getByRole('button', { name: 'Pick test house' }))
    expect(screen.getByText(/Selected: house in N10/i)).toBeInTheDocument()
    await user.click(screen.getByRole('link', { name: 'Continue' }))
    expect(screen.getByText('Capture step')).toBeInTheDocument()
    await user.click(screen.getByRole('link', { name: 'Start' }))
    expect(screen.getByText(/Selected: house in N10/i)).toBeInTheDocument()
  })
})
