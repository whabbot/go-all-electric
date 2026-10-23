import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api, isMockMode, type EpcAddress } from '../api'
import { useSession } from '../context/SessionContext'

export function StartScreen() {
  const { address, setAddress, placeLabel } = useSession()
  const [postcode, setPostcode] = useState(isMockMode() ? 'N10 2AB' : '')
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

        {address ? (
          <div className="selected-house">
            <p>
              <strong>Selected: {placeLabel}</strong>
              {address.current_energy_efficiency_band && <> · EPC band {address.current_energy_efficiency_band}</>}
            </p>
            <p className="subtle">From here on we show the postcode district only.</p>
            <button
              type="button"
              className="btn"
              onClick={() => {
                setAddress(null)
                setResults([])
              }}
            >
              Choose a different house
            </button>
          </div>
        ) : (
          results.length > 0 && (
            <ul className="address-list">
              {results.map((a) => (
                <li key={a.certificate_id}>
                  <button
                    type="button"
                    onClick={() => {
                      setAddress(a)
                      setResults([])
                      // Only the district stays on screen once a house is picked.
                      setPostcode('')
                    }}
                  >
                    <strong>{a.address}</strong>
                    <span>
                      EPC {a.current_energy_efficiency_band ?? '?'}, registered {a.registration_date.slice(0, 10)}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )
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
