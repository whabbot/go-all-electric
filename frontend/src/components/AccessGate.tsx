import { useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { isMockMode } from '../api/client'

/** Older builds kept the code itself in localStorage; remove it from those browsers. */
const LEGACY_CODE_KEY = 'gae-access-code'

const CONNECT_ERROR = 'Could not connect. Please try again.'

export function AccessGate({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(isMockMode())
  const [checking, setChecking] = useState(!isMockMode())
  const [code, setCode] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    try {
      localStorage.removeItem(LEGACY_CODE_KEY)
    } catch {
      /* storage unavailable */
    }
    const required = () => {
      setReady(false)
      setError('Please enter your access code again.')
    }
    const controller = new AbortController()
    window.addEventListener('gae-access-required', required)
    if (!isMockMode()) {
      void fetch('/api/access', { credentials: 'same-origin', signal: controller.signal })
        .then((res) => {
          if (res.ok) setReady(true)
          else if (res.status !== 401) setError(CONNECT_ERROR)
        })
        .catch(() => {
          if (!controller.signal.aborted) setError(CONNECT_ERROR)
        })
        .finally(() => {
          if (!controller.signal.aborted) setChecking(false)
        })
    }
    return () => {
      controller.abort()
      window.removeEventListener('gae-access-required', required)
    }
  }, [])

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setError('')
    setChecking(true)
    try {
      // The server answers with an HttpOnly session cookie; the code is not kept anywhere.
      const res = await fetch('/api/session', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code }),
      })
      if (!res.ok) {
        setError(res.status === 401
          ? 'Incorrect access code. Please try again.'
          : res.status === 429
            ? 'Too many attempts. Please wait a few minutes and try again.'
            : CONNECT_ERROR)
        return
      }
      setCode('')
      setReady(true)
    } catch {
      setError(CONNECT_ERROR)
    } finally {
      setChecking(false)
    }
  }

  if (ready) return children
  return (
    <main className="app-main">
      <section className="screen">
        <h1>Go All-Electric</h1>
        {checking ? <p role="status">Connecting…</p> : (
          <form className="card" onSubmit={(event) => void submit(event)}>
            <label htmlFor="access-code">Enter access code</label>
            <input
              id="access-code"
              type="password"
              autoComplete="current-password"
              required
              value={code}
              onChange={(event) => setCode(event.target.value)}
            />
            <p><button type="submit" className="btn primary">Continue</button></p>
            {error && <p className="error" role="alert">{error}</p>}
          </form>
        )}
      </section>
    </main>
  )
}
