import type { AnalysisBundle } from '../api'
import { RangeValue } from './RangeValue'

const MAX_KW = 12

export function EstimateHero({ analysis }: { analysis: AnalysisBundle }) {
  const { measured, fabric, cross_check: check } = analysis
  const verdictLabel =
    check.verdict === 'fabric_higher'
      ? 'Fabric calc reads higher than your bills'
      : check.verdict === 'measured_higher'
        ? 'Your bills read higher than the fabric calc'
        : 'Estimates agree'

  return (
    <section className="hero-estimates">
      <p className="hero-tagline">It doesn&apos;t trust its own model. It checks it against what your house actually used.</p>
      <div className={`verdict-banner verdict-${check.verdict}`}>
        <strong>{verdictLabel}</strong>
        <p>
          Fabric is about{' '}
          <RangeValue range={check.ratio} decimals={2} unit="×" /> higher than measured (ratio).
        </p>
      </div>

      <div className="estimate-columns">
        <div className="estimate-card estimate-b">
          <h2>Estimate B — measured</h2>
          <p className="estimate-sub">From your gas bill &amp; degree days</p>
          <div className="kw-display">
            <RangeValue range={measured.design_load_kw} unit=" kW" decimals={1} />
          </div>
          <RangeBand range={measured.design_load_kw} color="var(--color-measured)" label="B" />
        </div>

        <div className="estimate-card estimate-a">
          <h2>Estimate A — fabric</h2>
          <p className="estimate-sub">Installer-style from EPC + photos</p>
          <div className="kw-display">
            <RangeValue range={fabric.design_load_kw} unit=" kW" decimals={1} />
          </div>
          <RangeBand range={fabric.design_load_kw} color="var(--color-fabric)" label="A" />
        </div>
      </div>

      <div className="reasons-block">
        <h3>Why they disagree — ranked</h3>
        <ol className="reasons-list">
          {check.reasons.map((r) => (
            <li key={r.code}>
              <div className="reason-head">
                <span className="reason-share">{Math.round(r.share_of_gap * 100)}% of gap</span>
                <span className="reason-code">{r.code.replaceAll('_', ' ')}</span>
              </div>
              <p>{r.explanation}</p>
            </li>
          ))}
        </ol>
      </div>
    </section>
  )
}

function RangeBand({ range, color, label }: { range: { low: number; central: number; high: number }; color: string; label: string }) {
  const left = (range.low / MAX_KW) * 100
  const width = ((range.high - range.low) / MAX_KW) * 100
  const mid = (range.central / MAX_KW) * 100
  return (
    <div className="range-band-wrap" aria-hidden="true">
      <div className="range-band-track">
        <div
          className="range-band-fill"
          style={{ left: `${left}%`, width: `${width}%`, background: color }}
        />
        <div className="range-band-mid" style={{ left: `${mid}%`, borderColor: color }} title={label} />
      </div>
      <div className="range-band-scale">
        <span>0</span>
        <span>{MAX_KW} kW</span>
      </div>
    </div>
  )
}
