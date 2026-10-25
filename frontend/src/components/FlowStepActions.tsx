import { Link } from 'react-router-dom'
import { parseBillDetails } from '../lib/billDetails'
import {
  canReachNextStep,
  FLOW_STEPS,
  isStepOptional,
  nextPath,
  prevPath,
  type FlowPath,
} from '../lib/flow'
import { useFlow } from '../context/FlowContext'
import { useSession } from '../context/SessionContext'

function stepLabel(path: FlowPath): string {
  return FLOW_STEPS.find((s) => s.path === path)?.label ?? 'Next step'
}

export function FlowStepActions() {
  const { currentPath, visited } = useFlow()
  const session = useSession()

  const flowSession = {
    address: session.address,
    analysis: session.analysis,
    samSampleLoaded: session.samSampleLoaded,
  }

  const back = prevPath(currentPath)
  const next = nextPath(currentPath, flowSession)
  const canNext = canReachNextStep(currentPath, flowSession, visited)
  const optional = isStepOptional(currentPath, flowSession)

  let skipTarget: FlowPath | null = null
  if (optional && currentPath === '/cost') skipTarget = '/spec'

  const bill = parseBillDetails(session.billPeriods)
  const billIncomplete = currentPath === '/capture' && Boolean(bill.error && !bill.known)
  const area = session.houseDetails.floor_area_m2
  const houseIncomplete = currentPath === '/' && area != null && (!Number.isFinite(area) || area < 10 || area > 1000)
  const forwardReady = Boolean(next && canNext && !billIncomplete && !houseIncomplete)

  const hasUncheckedQuotes =
    currentPath === '/quotes' &&
    session.quotes.some((q) => q.group.pages.length > 0 && !q.result)

  let forwardLabel =
    currentPath === '/' ? 'Continue' : next ? `Next: ${stepLabel(next)}` : 'Next'
  if (currentPath === '/quotes' && hasUncheckedQuotes && next === '/plan') {
    forwardLabel = 'Continue without checking'
  }

  return (
    <div className="flow-actions" aria-label="Step navigation">
      {back ? (
        <Link className="btn" to={back}>
          Back
        </Link>
      ) : (
        <span />
      )}
      <div className="flow-actions-forward">
        {skipTarget && (
          <Link className="btn" to={skipTarget}>
            Skip
          </Link>
        )}
        {forwardReady && next && (
          <Link
            className={
              currentPath === '/quotes' && hasUncheckedQuotes ? 'btn' : 'btn primary'
            }
            to={next}
          >
            {forwardLabel}
          </Link>
        )}
        {(billIncomplete || houseIncomplete) && <button type="button" className="btn primary" disabled>{forwardLabel}</button>}
        {!next && currentPath === '/pack' && <span className="subtle">End of flow</span>}
      </div>
    </div>
  )
}
