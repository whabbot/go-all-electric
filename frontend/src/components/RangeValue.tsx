import type { Confidence, Exact, Range } from '../api'
import { formatGBP, formatGBPRange } from '../lib/format'

type Props = {
  range: Range
  unit?: string
  decimals?: number
  className?: string
  /** Format values as GBP (auto-detected when unit contains £). */
  money?: boolean
}

export function RangeValue({ range, unit = '', decimals = 1, className = '', money }: Props) {
  const isMoney = money ?? unit.includes('£')
  if (isMoney) {
    const suffix = unit.replace(/£/g, '').trim()
    return (
      <span className={`range-value ${className}`} title="Low – central – high estimate">
        {formatGBPRange(range.low, range.central, range.high, suffix ? ` ${suffix}` : '')}
      </span>
    )
  }
  const fmt = (n: number) => n.toFixed(decimals)
  return (
    <span className={`range-value ${className}`} title="Low – central – high estimate">
      <span className="range-low">{fmt(range.low)}</span>
      <span className="range-sep">–</span>
      <strong className="range-central">{fmt(range.central)}</strong>
      <span className="range-sep">–</span>
      <span className="range-high">{fmt(range.high)}</span>
      {unit ? <span className="range-unit">{unit}</span> : null}
    </span>
  )
}

export function ExactValue({ exact, unit = '', decimals = 0 }: { exact: Exact; unit?: string; decimals?: number }) {
  const isMoney = unit.includes('£')
  const value = isMoney ? formatGBP(exact.value) : exact.value.toFixed(decimals)
  return (
    <span className="exact-value" title={`Confidence: ${exact.confidence}`}>
      <strong>{value}</strong>
      {!isMoney && unit ? <span className="range-unit">{unit}</span> : null}
      <span className={`conf conf-${exact.confidence}`}>{exact.confidence}</span>
    </span>
  )
}

export function ConfidenceTag({ confidence }: { confidence: Confidence }) {
  return <span className={`conf conf-${confidence}`}>{confidence}</span>
}
