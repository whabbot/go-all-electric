import type { Confidence, Exact, Range } from '../api'

type Props = {
  range: Range
  unit?: string
  decimals?: number
  className?: string
}

export function RangeValue({ range, unit = '', decimals = 1, className = '' }: Props) {
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
  return (
    <span className="exact-value" title={`Confidence: ${exact.confidence}`}>
      <strong>{exact.value.toFixed(decimals)}</strong>
      {unit ? <span className="range-unit">{unit}</span> : null}
      <span className={`conf conf-${exact.confidence}`}>{exact.confidence}</span>
    </span>
  )
}

export function ConfidenceTag({ confidence }: { confidence: Confidence }) {
  return <span className={`conf conf-${confidence}`}>{confidence}</span>
}
