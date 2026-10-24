import { useSession } from '../context/SessionContext'
import { RadiatorVideoResults } from '../components/RadiatorVideoResults'
import { ExactValue, HeroKwStack } from '../components/RangeValue'
import { specRoomName } from '../lib/knownDetails'

export function SpecScreen() {
  const { analysis, radiatorVideoResult, placeLabel, radiatorLabels } = useSession()
  if (!analysis) return null

  const spec = analysis.bundle.target_spec
  const fromBills = analysis.size_basis === 'measured'
  const videoResult = analysis.radiator_video ?? radiatorVideoResult

  return (
    <section className="screen spec-screen">
      <h1>Target spec</h1>
      {placeLabel && <p className="place-label">{placeLabel}</p>}
      <p className="lede">What a good installation should look like for this home — second opinion, not a survey.</p>

      <div className="card highlight">
        <h2>Heat pump size</h2>
        <HeroKwStack range={spec.size_kw} decimals={0} className="spec-kw-display" />
        <p className="subtle">
          {fromBills
            ? 'Sized from measured load, not the fabric high estimate.'
            : "Sized from the fabric estimate only (no usable bill), which often reads high. Add a bill to size from what the house actually used."}
        </p>
      </div>

      <div className="card">
        <h2>Maximum flow temperature</h2>
        <ExactValue exact={spec.max_flow_temp_c} unit=" °C" decimals={0} />
        {spec.flow_temp_needed_by_current_radiators_c && (
          <p>
            Worst room needs about{' '}
            <ExactValue exact={spec.flow_temp_needed_by_current_radiators_c} unit=" °C" decimals={0} /> with
            existing radiators.
          </p>
        )}
      </div>

      <div className="card">
        <h2>Radiators</h2>
        {spec.radiators.length === 0 && !videoResult && (
          <p className="subtle">
            Couldn&apos;t check radiators: add a clear radiator photo with a tape measure across it,
            or film your radiators.
          </p>
        )}
        <ul className="radiator-list">
          {spec.radiators.map((r) => (
            <li key={r.room} className={`rad-${r.status}`}>
              <strong>{specRoomName(r.room, radiatorLabels, analysis.readings)}</strong>
              <span className={`status-pill status-${r.status}`}>{r.status}</span>
              <p>
                At {r.flow_temp_c}°C: {Math.round(r.output_w)} W output vs {Math.round(r.heat_loss_w)} W loss
                {analysis.defaults.some((d) => d.input === 'radiators')
                  ? ' (rating and room loss are named estimates, low confidence)'
                  : ''}
              </p>
              {r.status === 'upsize' && (
                <p className="subtle">Consider ~{Math.round(r.required_output_dt50_w)} W (ΔT50) or higher flow.</p>
              )}
            </li>
          ))}
        </ul>
        {videoResult && <RadiatorVideoResults result={videoResult} />}
      </div>

      <div className="card grant-card">
        <h2>Grant</h2>
        <p className="grant-amount">
          <ExactValue exact={spec.grant.amount_gbp} unit=" £" decimals={0} />
        </p>
        <p>{spec.grant.note}</p>
      </div>

    </section>
  )
}
