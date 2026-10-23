import { NavLink } from 'react-router-dom'

const STEPS = [
  { to: '/', label: 'Start' },
  { to: '/capture', label: 'Photos' },
  { to: '/estimates', label: 'Estimates' },
  { to: '/cost', label: 'Costs' },
  { to: '/spec', label: 'Spec' },
  { to: '/quotes', label: 'Quotes' },
  { to: '/plan', label: 'Plan' },
] as const

export function DemoNav() {
  return (
    <nav className="demo-nav" aria-label="Demo flow">
      {STEPS.map((s) => (
        <NavLink key={s.to} to={s.to} end={s.to === '/'} className={({ isActive }) => (isActive ? 'active' : '')}>
          {s.label}
        </NavLink>
      ))}
    </nav>
  )
}
