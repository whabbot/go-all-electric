import { isMockMode } from '../api'
import type { Session } from '../context/flowSession'

export const FLOW_STEPS = [
  { path: '/', label: 'Start' },
  { path: '/capture', label: 'Photos' },
  { path: '/estimates', label: 'Estimates' },
  { path: '/cost', label: 'Costs' },
  { path: '/spec', label: 'Spec' },
  { path: '/quotes', label: 'Quotes' },
  { path: '/plan', label: 'Plan' },
  { path: '/pack', label: 'Pack' },
] as const

export type FlowPath = (typeof FLOW_STEPS)[number]['path']

export function flowPathIndex(path: string): number {
  const i = FLOW_STEPS.findIndex((s) => s.path === path)
  return i >= 0 ? i : 0
}

export function startComplete(session: Session): boolean {
  return Boolean(session.address) || isMockMode() || session.samSampleLoaded
}

export function captureComplete(session: Session, visited: ReadonlySet<string>): boolean {
  return startComplete(session) && visited.has('/capture')
}

export function estimatesComplete(session: Session): boolean {
  return session.analysis != null
}

export function costStepOptional(session: Session): boolean {
  return !session.analysis?.bundle.costs_by_flow_temp.length
}

export function costComplete(session: Session, visited: ReadonlySet<string>): boolean {
  if (!estimatesComplete(session)) return false
  if (costStepOptional(session)) return true
  return visited.has('/cost')
}

export function specComplete(session: Session, visited: ReadonlySet<string>): boolean {
  if (!estimatesComplete(session)) return false
  if (!costComplete(session, visited)) return false
  return visited.has('/spec')
}

export function quotesStepOptional(): boolean {
  return true
}

export function quotesComplete(session: Session, visited: ReadonlySet<string>): boolean {
  if (!specComplete(session, visited)) return false
  return true
}

export function planComplete(session: Session, visited: ReadonlySet<string>): boolean {
  if (!session.analysis?.plan) return false
  if (!specComplete(session, visited)) return false
  return visited.has('/plan')
}

export function packComplete(session: Session, visited: ReadonlySet<string>): boolean {
  if (!planComplete(session, visited)) return false
  return visited.has('/pack')
}

function stepComplete(path: FlowPath, session: Session, visited: ReadonlySet<string>): boolean {
  switch (path) {
    case '/':
      return startComplete(session)
    case '/capture':
      return captureComplete(session, visited)
    case '/estimates':
      return estimatesComplete(session)
    case '/cost':
      return costComplete(session, visited)
    case '/spec':
      return specComplete(session, visited)
    case '/quotes':
      return quotesComplete(session, visited)
    case '/plan':
      return planComplete(session, visited)
    case '/pack':
      return packComplete(session, visited)
    default:
      return false
  }
}

function stepAccessible(path: FlowPath, session: Session): boolean {
  if (path === '/plan') return Boolean(session.analysis?.plan)
  return true
}

/** Highest step index the user may open (0-based). */
export function furthestReachableIndex(session: Session, visited: ReadonlySet<string>): number {
  if (session.samSampleLoaded || isMockMode()) return FLOW_STEPS.length - 1

  for (let i = 0; i < FLOW_STEPS.length; i++) {
    if (i === 0) continue
    const prev = FLOW_STEPS[i - 1].path
    if (!stepComplete(prev, session, visited)) return i - 1
    const path = FLOW_STEPS[i].path
    if (!stepAccessible(path, session)) return i - 1
  }
  return FLOW_STEPS.length - 1
}

export function canAdvanceFrom(path: FlowPath, session: Session, visited: ReadonlySet<string>): boolean {
  return stepComplete(path, session, visited)
}

export function nextPath(path: FlowPath, session: Session): FlowPath | null {
  const i = flowPathIndex(path)
  if (path === '/estimates' && session.analysis) {
    return session.analysis.bundle.costs_by_flow_temp.length ? '/cost' : '/spec'
  }
  if (path === '/quotes') return session.analysis?.plan ? '/plan' : null
  if (i >= FLOW_STEPS.length - 1) return null
  const candidate = FLOW_STEPS[i + 1].path
  if (!stepAccessible(candidate, session)) return null
  return candidate
}

export function prevPath(path: FlowPath): FlowPath | null {
  const i = flowPathIndex(path)
  if (i <= 0) return null
  return FLOW_STEPS[i - 1].path
}

export function isStepOptional(path: FlowPath, session: Session): boolean {
  if (path === '/cost') return costStepOptional(session)
  if (path === '/quotes') return quotesStepOptional()
  return false
}
