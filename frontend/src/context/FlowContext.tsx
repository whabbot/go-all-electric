import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'
import { useLocation } from 'react-router-dom'
import {
  FLOW_STEPS,
  flowPathIndex,
  furthestReachableIndex,
  type FlowPath,
} from '../lib/flow'
import { useSession } from './SessionContext'

const VISITED_KEY = 'gae-flow-visited'

function loadVisited(): Set<string> {
  try {
    const raw = sessionStorage.getItem(VISITED_KEY)
    if (!raw) return new Set()
    const list = JSON.parse(raw) as string[]
    return new Set(list)
  } catch {
    return new Set()
  }
}

function saveVisited(visited: Set<string>) {
  try {
    sessionStorage.setItem(VISITED_KEY, JSON.stringify([...visited]))
  } catch {
    /* ignore */
  }
}

type FlowContextValue = {
  visited: Set<string>
  markVisited: (path: string) => void
  currentIndex: number
  furthestIndex: number
  currentPath: FlowPath
}

const FlowContext = createContext<FlowContextValue | null>(null)

export function FlowProvider({ children }: { children: ReactNode }) {
  const session = useSession()
  const location = useLocation()
  const [visited, setVisited] = useState<Set<string>>(loadVisited)

  const markVisited = useCallback((path: string) => {
    setVisited((prev) => {
      if (prev.has(path)) return prev
      const next = new Set(prev)
      next.add(path)
      saveVisited(next)
      return next
    })
  }, [])

  const flowSession = useMemo(
    () => ({
      address: session.address,
      analysis: session.analysis,
      samSampleLoaded: session.samSampleLoaded,
    }),
    [session.address, session.analysis, session.samSampleLoaded],
  )

  const currentPath = (FLOW_STEPS.find((s) => s.path === location.pathname)?.path ?? '/') as FlowPath
  const currentIndex = flowPathIndex(location.pathname)
  const furthestIndex = furthestReachableIndex(flowSession, visited)

  const value = useMemo(
    () => ({
      visited,
      markVisited,
      currentIndex,
      furthestIndex,
      currentPath,
    }),
    [visited, markVisited, currentIndex, furthestIndex, currentPath],
  )

  return <FlowContext.Provider value={value}>{children}</FlowContext.Provider>
}

export function useFlow() {
  const ctx = useContext(FlowContext)
  if (!ctx) throw new Error('useFlow outside provider')
  return ctx
}
