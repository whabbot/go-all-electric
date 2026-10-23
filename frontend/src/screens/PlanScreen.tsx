import { Link } from 'react-router-dom'

const STEPS = [
  { id: 'supply', title: 'Supply check', status: 'upcoming', detail: 'Fuse cutout & headroom — from your photo' },
  { id: 'heatpump', title: 'Heat pump + grant', status: 'current', detail: '5–7 kW target, BUS grant £7,500' },
  { id: 'solar', title: 'Solar', status: 'upcoming', detail: 'Roof potential — coming soon' },
  { id: 'ev', title: 'EV charging', status: 'upcoming', detail: 'Sequenced after heat & solar' },
]

export function PlanScreen() {
  return (
    <section className="screen plan-screen">
      <h1>Go all-electric plan</h1>
      <p className="lede">One sequenced path — supply, heat pump, solar, then EV.</p>

      <ol className="plan-steps">
        {STEPS.map((s) => (
          <li key={s.id} className={`plan-step plan-${s.status}`}>
            <span className="plan-marker" />
            <div>
              <h2>{s.title}</h2>
              <p>{s.detail}</p>
            </div>
          </li>
        ))}
      </ol>

      <blockquote className="advice-quote">It advises; you decide.</blockquote>

      <p className="footer-note">Nothing in this app contacts installers or network operators.</p>

      <p className="cta-row">
        <Link className="btn" to="/">Back to start</Link>
      </p>
    </section>
  )
}
