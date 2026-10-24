import { Link } from 'react-router-dom'
import {
  canAdvanceFrom,
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
  const canNext = canAdvanceFrom(currentPath, flowSession, visited)
  const optional = isStepOptional(currentPath, flowSession)

  let skipTarget: FlowPath | null = null
  if (optional && currentPath === '/cost') skipTarget = '/spec'
  if (optional && currentPath === '/quotes' && session.analysis?.plan) skipTarget = '/plan'

  const forwardLabel =
    currentPath === '/' ? 'Continue' : next ? `Next: ${stepLabel(next)}` : 'Next'

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
        {next && canNext && (
          <Link className="btn primary" to={next}>
            {forwardLabel}
          </Link>
        )}
        {!next && currentPath === '/pack' && canNext && <span className="subtle">End of flow</span>}
      </div>
    </div>
  )
}
