import { useEffect, useState } from 'react'
import { api, type VerificationLogEntry } from '../api'

export function VerificationLogPanel({ visible }: { visible: boolean }) {
  const [entries, setEntries] = useState<VerificationLogEntry[]>([])
  const [shown, setShown] = useState(0)

  useEffect(() => {
    if (!visible) return
    let cancelled = false
    void api.streamVerificationLog().then((all) => {
      if (cancelled) return
      setEntries(all)
      setShown(0)
    })
    return () => {
      cancelled = true
    }
  }, [visible])

  useEffect(() => {
    if (shown >= entries.length) return
    const t = setTimeout(() => setShown((s) => s + 1), 450)
    return () => clearTimeout(t)
  }, [shown, entries.length])

  if (!visible || entries.length === 0) return null

  return (
    <aside className="verification-log" aria-live="polite">
      <h3>Verification log</h3>
      <ol>
        {entries.slice(0, shown).map((e) => (
          <li key={e.id} className={e.passed ? 'log-pass' : 'log-fail'}>
            <span className="log-step">{e.step}</span>
            <span className="log-check">{e.check}</span>
            <span className="log-model">{e.model}</span>
            <span className="log-action">{e.action}</span>
          </li>
        ))}
      </ol>
    </aside>
  )
}
