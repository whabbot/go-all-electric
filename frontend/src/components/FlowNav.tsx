import { useEffect, useRef } from 'react'
import { Link } from 'react-router-dom'
import { FLOW_STEPS } from '../lib/flow'
import { useFlow } from '../context/FlowContext'

export function FlowNav() {
  const { currentIndex, furthestIndex } = useFlow()
  const activeRef = useRef<HTMLAnchorElement | null>(null)

  useEffect(() => {
    const el = activeRef.current
    if (el && typeof el.scrollIntoView === 'function') {
      el.scrollIntoView({ inline: 'center', block: 'nearest', behavior: 'smooth' })
    }
  }, [currentIndex])

  const progressPct = ((currentIndex + 1) / FLOW_STEPS.length) * 100

  return (
    <nav className="flow-nav" aria-label="Guided flow">
      <div className="flow-progress-track" aria-hidden="true">
        <span style={{ width: `${progressPct}%` }} />
      </div>
      <p className="flow-progress" aria-live="polite">
        Step {currentIndex + 1} of {FLOW_STEPS.length}: {FLOW_STEPS[currentIndex].label}
      </p>
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
              <span className="flow-step-upcoming" aria-disabled="true">
                {step.label}
              </span>
            </li>
          )
        })}
      </ol>
    </nav>
  )
}
