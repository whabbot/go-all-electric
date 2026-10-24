import { useEffect, useRef, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { FLOW_STEPS, isStepOptional } from '../lib/flow'
import { useFlow } from '../context/FlowContext'
import { useSession } from '../context/SessionContext'

type Props = {
  brand: ReactNode
}

export function FlowNav({ brand }: Props) {
  const { currentPath, currentIndex, furthestIndex } = useFlow()
  const session = useSession()
  const activeRef = useRef<HTMLAnchorElement | null>(null)

  useEffect(() => {
    const el = activeRef.current
    if (el && typeof el.scrollIntoView === 'function') {
      el.scrollIntoView({ inline: 'center', block: 'nearest', behavior: 'smooth' })
    }
  }, [currentIndex])

  const progressPct = ((currentIndex + 1) / FLOW_STEPS.length) * 100
  const flowSession = {
    address: session.address,
    analysis: session.analysis,
    samSampleLoaded: session.samSampleLoaded,
  }
  const stepOptional = isStepOptional(currentPath, flowSession)

  return (
    <nav className="flow-nav" aria-label="Guided flow">
      <div className="app-header-top">
        {brand}
        <p className="flow-progress" aria-live="polite">
          Step {currentIndex + 1}/{FLOW_STEPS.length}: {FLOW_STEPS[currentIndex].label}
          {stepOptional ? ' (optional)' : ''}
        </p>
      </div>
      <div className="flow-progress-track" aria-hidden="true">
        <span style={{ width: `${progressPct}%` }} />
      </div>
      <ol className="flow-steps">
        {FLOW_STEPS.map((step, index) => {
          const reachable = index <= furthestIndex
          const current = index === currentIndex
          const done = reachable && index < currentIndex
          if (reachable) {
            return (
              <li key={step.path}>
                <Link
                  ref={current ? activeRef : undefined}
                  to={step.path}
                  className={[current ? 'active' : undefined, done ? 'done' : undefined].filter(Boolean).join(' ') || undefined}
                  aria-current={current ? 'step' : undefined}
                >
                  {step.label}
                </Link>
              </li>
            )
          }
          return (
            <li key={step.path}>
              <span
                className="flow-step-upcoming"
                aria-disabled="true"
                title="Complete earlier steps first"
              >
                {step.label}
                <span className="flow-step-locked-hint"> (locked)</span>
              </span>
            </li>
          )
        })}
      </ol>
    </nav>
  )
}
