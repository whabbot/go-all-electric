import { useState } from 'react'
import { api, isMockMode, type EpcAddress } from '../api'
import { HouseDetails } from '../components/HouseDetails'
import { Alert } from '../components/Alert'
import { useSession } from '../context/SessionContext'

export function StartScreen() {
  const { address, setAddress, placeLabel, loadSamSample: loadSample, clearHouseSelection } =
    useSession()
  const [postcode, setPostcode] = useState(isMockMode() && !address ? 'N10 2AB' : '')
  const [results, setResults] = useState<EpcAddress[]>([])
  const loadSamSample = () => {
    loadSample()
    setResults([])
    // As when a house is picked: only the district stays on screen, never the full postcode.
    setPostcode('')
  }
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [emptyPostcode, setEmptyPostcode] = useState(false)

  const search = async () => {
    setLoading(true)
    setError(null)
    setEmptyPostcode(false)
    try {
      const list = await api.searchEpcAddresses(postcode)
      setResults(list)
      if (list.length === 0) {
        setEmptyPostcode(true)
        setError(null)
      }
    } catch (e) {
      const message = e instanceof Error ? e.message : 'Search failed'
      const providerOutage =
        message.includes("Couldn't read the data provider") ||
        message.includes('rate limited') ||
        message.includes('credentials were rejected')
      setError(providerOutage ? message : 'EPC lookup is temporarily unavailable — try again in a few minutes.')
      setEmptyPostcode(false)
    } finally {
      setLoading(false)
    }
  }

  return (
    <section className="screen start-screen">
      <h1>Go All-Electric</h1>
      <p className="hero-tagline">
        Plan your move off gas — heat pump, solar, and EV charging in the right order.
      </p>
      <p className="lede">
        Your gas bills have already measured your house. Go All-Electric checks installer maths against
        that real use, sizes the kit, and lays out costs — then you decide what to do next.
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
        {emptyPostcode && (
          <Alert
            variant="info"
            title="No EPC certificates for this postcode"
            action={
              <>
                {isMockMode() && (
                  <button type="button" className="btn primary" onClick={loadSamSample}>
                    Use Sam&apos;s sample
                  </button>
                )}
              </>
            }
          >
            That postcode is valid, but we did not find any lodged certificates. Try another house
            {isMockMode()
              ? ', or continue with the offline demo if you are exploring the flow.'
              : '.'}
          </Alert>
        )}
        {error && (
          <Alert
            variant="error"
            title="EPC lookup unavailable"
            action={
              <button type="button" className="btn" onClick={() => void search()}>
                Try again
              </button>
            }
          >
            {error}
          </Alert>
        )}

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
                clearHouseSelection()
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

      <HouseDetails />

      {isMockMode() && (
        <p className="cta-row">
          <button type="button" className="btn" onClick={loadSamSample}>
            Load Sam&apos;s sample (demo)
          </button>
        </p>
      )}

      <p className="footer-note">Nothing is sent to installers or network operators.</p>
    </section>
  )
}
