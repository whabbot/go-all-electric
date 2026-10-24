import { useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { isMockMode } from '../api/client'

/** Older builds kept the code itself in localStorage; remove it from those browsers. */
const LEGACY_CODE_KEY = 'gae-access-code'

const CONNECT_ERROR = 'Could not connect. Please try again.'

function EyeIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
      <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  )
}

function EyeOffIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
      <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94" />
      <path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19" />
      <path d="M1 1l22 22" />
      <path d="M14.12 14.12a3 3 0 1 1-4.24-4.24" />
    </svg>
  )
}

export function AccessGate({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(isMockMode())
  const [checking, setChecking] = useState(!isMockMode())
  const [code, setCode] = useState('')
  const [showCode, setShowCode] = useState(false)
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
            <div className="access-code-field">
              <input
                id="access-code"
                type={showCode ? 'text' : 'password'}
                autoComplete="current-password"
                autoCapitalize={showCode ? 'off' : undefined}
                autoCorrect={showCode ? 'off' : undefined}
                spellCheck={showCode ? false : undefined}
                required
                value={code}
                onChange={(event) => setCode(event.target.value)}
              />
              <button
                type="button"
                className="access-code-toggle"
                aria-label={showCode ? 'Hide access code' : 'Show access code'}
                aria-pressed={showCode}
                onClick={() => setShowCode((visible) => !visible)}
              >
                {showCode ? <EyeOffIcon /> : <EyeIcon />}
              </button>
            </div>
            <p><button type="submit" className="btn primary">Continue</button></p>
            {error && <p className="error" role="alert">{error}</p>}
          </form>
        )}
      </section>
    </main>
  )
}
