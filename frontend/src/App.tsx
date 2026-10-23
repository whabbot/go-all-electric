import { useEffect, useState } from 'react'

type Health = {
  status: string
  configured: Record<string, boolean>
}

// Placeholder page: proves the frontend can reach the backend. The real UI replaces this.
function App() {
  const [health, setHealth] = useState<Health | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetch('/api/health')
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        return res.json() as Promise<Health>
      })
      .then(setHealth)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : String(err)))
  }, [])

  return (
    <main>
      <h1>Go All-Electric</h1>
      <p>Your gas bills have already measured your house; we use that to check the installer's maths.</p>
      <section aria-live="polite">
        <h2>Backend</h2>
        {error && <p>Backend unreachable: {error}. Start it with <code>uv run uvicorn gae.main:app</code>.</p>}
        {!error && !health && <p>Checking…</p>}
        {health && (
          <ul>
            <li>Status: {health.status}</li>
            {Object.entries(health.configured).map(([name, ok]) => (
              <li key={name}>
                {name}: {ok ? 'configured' : 'not configured'}
              </li>
            ))}
          </ul>
        )}
      </section>
      <p>
        <small>It advises; you decide.</small>
      </p>
    </main>
  )
}

export default App
