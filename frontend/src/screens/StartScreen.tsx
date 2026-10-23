import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type EpcAddress } from '../api'
import { useSession } from '../context/SessionContext'

export function StartScreen() {
  const { address, setAddress } = useSession()
  const [postcode, setPostcode] = useState(address?.postcode ?? 'N10 2AB')
  const [results, setResults] = useState<EpcAddress[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const search = async () => {
    setLoading(true)
    setError(null)
    try {
      const list = await api.searchEpcAddresses(postcode)
      setResults(list)
      if (list.length === 0) setError('No EPC records found — try a full postcode.')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Search failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <section className="screen start-screen">
      <h1>Sam&apos;s heat pump puzzle</h1>
      <p className="lede">
        A 1930s semi in London, a gas combi, and three installer quotes: <strong>6 kW</strong>,{' '}
        <strong>9 kW</strong>, and <strong>12 kW</strong>. Which size is right — and will a heat pump
        actually be cheaper?
      </p>
      <p className="lede subtle">
        Your gas bills have already measured your house; we use that to check the installer&apos;s maths.
      </p>

      <div className="card">
        <label htmlFor="postcode">Postcode</label>
        <div className="row">
          <input
            id="postcode"
            type="text"
            autoComplete="postal-code"
            value={postcode}
            onChange={(e) => setPostcode(e.target.value)}
            placeholder="e.g. N10 2AB"
          />
          <button type="button" onClick={() => void search()} disabled={loading}>
            {loading ? 'Looking…' : 'Find EPC'}
          </button>
        </div>
        {error && <p className="error">{error}</p>}

        {results.length > 0 && (
          <ul className="address-list">
            {results.map((a) => (
              <li key={a.lmk_key}>
                <button
                  type="button"
                  className={address?.lmk_key === a.lmk_key ? 'selected' : ''}
                  onClick={() => setAddress(a)}
                >
                  <strong>{a.address}</strong>
                  <span>
                    {a.property_type}, {a.floor_area_m2} m², built {a.year_built}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {address && (
        <p className="cta-row">
          <Link className="btn primary" to="/capture">
            Continue — add photos
          </Link>
        </p>
      )}

      <p className="footer-note">Nothing is sent to installers or network operators.</p>
    </section>
  )
}
