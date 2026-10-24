import type { AllElectricPlan, PlanStep } from '../api'
import { useSession } from '../context/SessionContext'

function stepClass(step: PlanStep): string {
  if (step.status === 'flagged') return 'plan-flagged'
  if (step.status === 'couldnt_tell') return 'plan-couldnt-tell'
  if (step.id === 'heat_pump') return 'plan-current'
  return 'plan-ok'
}

function PlanView({ plan }: { plan: AllElectricPlan }) {
  return (
    <section className="screen plan-screen">
      <h1>Your all-electric plan</h1>
      <p className="lede">Supply first, then heat pump and grant, solar, then EV — one sequenced path.</p>

      <ul className="plan-legend" aria-label="Plan step markers">
        <li><span className="plan-marker plan-flagged" aria-hidden="true" /> Action needed</li>
        <li><span className="plan-marker plan-current" aria-hidden="true" /> Current focus</li>
        <li><span className="plan-marker plan-ok" aria-hidden="true" /> Ready / later</li>
      </ul>

      <ol className="plan-steps">
        {plan.steps.map((step) => (
          <li key={step.id} className={`plan-step ${stepClass(step)}`}>
            <span
              className="plan-marker"
              aria-label={
                step.status === 'flagged'
                  ? 'Action needed'
                  : step.id === 'heat_pump'
                    ? 'Current focus'
                    : 'Ready or later step'
              }
            />
            <div>
              <h2>{step.title}</h2>
              <p className="plan-order-reason">{step.order_reason}</p>
              <p className="plan-headline">{step.headline}</p>
              {step.detail && <p className="subtle">{step.detail}</p>}
            </div>
          </li>
        ))}
      </ol>

      <blockquote className="advice-quote">It advises; you decide.</blockquote>

      <p className="footer-note">
        Nothing is sent to your network operator or installers.
      </p>

    </section>
  )
}

export function PlanScreen() {
  const { analysis } = useSession()

  if (!analysis?.plan) return null

  return <PlanView plan={analysis.plan} />
}
