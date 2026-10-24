import type { AnalysisBundle, Gap } from '../api'
import { RangeValue } from './RangeValue'

const MAX_KW = 12
const SAM_QUOTE_KW = [6, 9, 12]

export function EstimateHero({ analysis, billGap }: { analysis: AnalysisBundle; billGap: Gap | null }) {
  const { measured, fabric, cross_check: check } = analysis
  const verdictLabel = !check
    ? null
    : check.verdict === 'fabric_higher'
      ? 'Fabric calc reads higher than your bills'
      : check.verdict === 'measured_higher'
        ? 'Your bills read higher than the fabric calc'
        : 'Estimates agree'

  return (
    <section className="hero-estimates hero-estimates-layout">
      <p className="hero-tagline prose-measure">
        It doesn&apos;t trust its own model. It checks it against what your house actually used.
      </p>
      {check ? (
        <div className={`verdict-banner verdict-${check.verdict}`}>
          <strong>{verdictLabel}</strong>
          <p>
            Fabric ÷ measured: <strong className="ratio-central">{check.ratio.central.toFixed(2)}×</strong>{' '}
            <span className="subtle">
              (range <span className="range-value">{check.ratio.low.toFixed(2)}–{check.ratio.high.toFixed(2)}×</span>)
            </span>
          </p>
        </div>
      ) : (
        <div className="cannot-compare">
          <strong>Can&apos;t compare yet</strong>
          <p>{billGap?.message ?? 'No measured estimate: nothing to check the fabric calc against.'}</p>
          {billGap && <p className="subtle">{billGap.provide}</p>}
        </div>
      )}

      <div className="estimate-columns">
        <div className="estimate-card estimate-b card">
          <h2>Estimate B — measured</h2>
          <p className="estimate-sub">From your gas bill &amp; degree days</p>
          {measured ? (
            <>
              <div className="kw-display" data-hero>
                <RangeValue range={measured.design_load_kw} unit=" kW" decimals={1} />
              </div>
              <RangeBand range={measured.design_load_kw} color="var(--color-measured)" label="B" />
              {measured.caveats.length > 0 && (
                <p className="subtle">Caveats: {measured.caveats.map((c) => c.replaceAll('_', ' ')).join(', ')}</p>
              )}
            </>
          ) : (
            <p className="kw-display couldnt-tell" data-hero>Couldn&apos;t tell</p>
          )}
        </div>

        <div className="estimate-card estimate-a card">
          <h2>Estimate A — fabric</h2>
          <p className="estimate-sub">Installer-style from EPC + photos</p>
          <div className="kw-display" data-hero>
            <RangeValue range={fabric.design_load_kw} unit=" kW" decimals={1} />
          </div>
          <RangeBand range={fabric.design_load_kw} color="var(--color-fabric)" label="A" />
        </div>
      </div>

      <SharedKwAxis
        measured={measured?.design_load_kw ?? null}
        fabric={fabric.design_load_kw}
        quoteKw={SAM_QUOTE_KW}
      />

      {check && check.reasons.length > 0 && (
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
      )}
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

function SharedKwAxis({
  measured,
  fabric,
  quoteKw,
}: {
  measured: { low: number; central: number; high: number } | null
  fabric: { low: number; central: number; high: number }
  quoteKw: number[]
}) {
  return (
    <div className="shared-kw-axis" aria-label="Estimates and quoted sizes on one scale">
      <h3>Both estimates vs installer quote sizes (0–12 kW)</h3>
      <div className="shared-kw-axis-visual">
        <div className="shared-kw-axis-track">
          {measured && (
            <div
              className="shared-kw-band shared-kw-band--b"
              style={{
                left: `${(measured.low / MAX_KW) * 100}%`,
                width: `${((measured.high - measured.low) / MAX_KW) * 100}%`,
              }}
            />
          )}
          <div
            className="shared-kw-band shared-kw-band--a"
            style={{
              left: `${(fabric.low / MAX_KW) * 100}%`,
              width: `${((fabric.high - fabric.low) / MAX_KW) * 100}%`,
            }}
          />
          {quoteKw.map((kw) => (
            <div
              key={`tick-${kw}`}
              className={`shared-kw-quote-tick-line${kw === MAX_KW ? ' shared-kw-quote-tick-line--end' : ''}`}
              style={{ left: `${(kw / MAX_KW) * 100}%` }}
              aria-hidden="true"
            />
          ))}
        </div>
        <div className="shared-kw-axis-labels" aria-hidden="true">
          {quoteKw.map((kw) => (
            <span
              key={`label-${kw}`}
              className={`shared-kw-quote-label${kw === MAX_KW ? ' shared-kw-quote-label--end' : ''}`}
              style={{ left: `${(kw / MAX_KW) * 100}%` }}
            >
              {kw}
            </span>
          ))}
        </div>
      </div>
      <p className="subtle" style={{ marginTop: '1.75rem' }}>
        Blue band = measured (B), orange = fabric (A). Ticks = Sam&apos;s 6, 9 and 12 kW quotes.
      </p>
    </div>
  )
}
