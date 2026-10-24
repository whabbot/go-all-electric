import { Link } from 'react-router-dom'
import { FLOW_STEPS } from '../lib/flow'
import { useFlow } from '../context/FlowContext'

export function FlowNav() {
  const { currentIndex, furthestIndex } = useFlow()

  return (
    <nav className="flow-nav" aria-label="Guided flow">
      <p className="flow-progress" aria-live="polite">
        Step {currentIndex + 1} of {FLOW_STEPS.length}: {FLOW_STEPS[currentIndex].label}
      </p>
      <ol className="flow-steps">
        {FLOW_STEPS.map((step, index) => {
          const reachable = index <= furthestIndex
          const current = index === currentIndex
          if (reachable) {
            return (
              <li key={step.path}>
                <Link
                  to={step.path}
                  className={current ? 'active' : undefined}
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
