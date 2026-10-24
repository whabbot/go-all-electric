import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { AccessGate } from './components/AccessGate'
import { FlowNav } from './components/FlowNav'
import { FlowStepActions } from './components/FlowStepActions'
import { FlowStepGate } from './components/FlowStepGate'
import { FlowProvider } from './context/FlowContext'
import { SessionProvider } from './context/SessionContext'
import { CaptureScreen } from './screens/CaptureScreen'
import { CostScreen } from './screens/CostScreen'
import { EstimatesScreen } from './screens/EstimatesScreen'
import { PackScreen } from './screens/PackScreen'
import { PlanScreen } from './screens/PlanScreen'
import { QuotesScreen } from './screens/QuotesScreen'
import { SpecScreen } from './screens/SpecScreen'
import { StartScreen } from './screens/StartScreen'

function App() {
  return (
    <AccessGate>
      <SessionProvider>
        <BrowserRouter>
          <FlowProvider>
            <FlowStepGate>
              <div className="app-shell">
                <header className="app-header">
                  <p className="brand">Go All-Electric</p>
                  <FlowNav />
                </header>
                <main className="app-main">
                  <Routes>
                    <Route path="/" element={<StartScreen />} />
                    <Route path="/capture" element={<CaptureScreen />} />
                    <Route path="/estimates" element={<EstimatesScreen />} />
                    <Route path="/cost" element={<CostScreen />} />
                    <Route path="/spec" element={<SpecScreen />} />
                    <Route path="/quotes" element={<QuotesScreen />} />
                    <Route path="/plan" element={<PlanScreen />} />
                    <Route path="/pack" element={<PackScreen />} />
                  </Routes>
                  <FlowStepActions />
                </main>
                <footer className="app-footer">
                  <small>Second opinion with ranges — not financial advice. It advises; you decide.</small>
                </footer>
              </div>
            </FlowStepGate>
          </FlowProvider>
        </BrowserRouter>
      </SessionProvider>
    </AccessGate>
  )
}

export default App
