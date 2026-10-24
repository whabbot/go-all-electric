import { useEffect, type ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { FLOW_STEPS, flowPathIndex, furthestReachableIndex } from '../lib/flow'
import { useFlow } from '../context/FlowContext'
import { useSession } from '../context/SessionContext'

export function FlowStepGate({ children }: { children: ReactNode }) {
  const location = useLocation()
  const { markVisited, visited } = useFlow()
  const session = useSession()

  const flowSession = {
    address: session.address,
    analysis: session.analysis,
    samSampleLoaded: session.samSampleLoaded,
  }

  const path = location.pathname
  const index = flowPathIndex(path)
  const furthest = furthestReachableIndex(flowSession, visited)

  useEffect(() => {
    if (FLOW_STEPS.some((s) => s.path === path)) markVisited(path)
  }, [path, markVisited])

  if (!FLOW_STEPS.some((s) => s.path === path)) {
    return <>{children}</>
  }

  if (index > furthest) {
    return <Navigate to={FLOW_STEPS[furthest].path} replace />
  }

  return <>{children}</>
}
