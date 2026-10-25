import { Link } from 'react-router-dom'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ErrorBar,
  Label,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { useSession } from '../context/SessionContext'
import { RangeValue } from '../components/RangeValue'
import { formatGBP } from '../lib/format'

export function CostScreen() {
  const { analysis, placeLabel } = useSession()
  if (!analysis) return null
  if (analysis.bundle.costs_by_flow_temp.length === 0) {
    const gap = analysis.gaps.find((g) => g.input === 'gas_bill')
    return (
      <section className="screen cost-screen">
        <h1>Costs</h1>
        <div className="cannot-compare">
          <strong>Couldn&apos;t tell without a usable gas bill</strong>
          <p>Running costs compare against what you actually spend on gas, so we need your bill.</p>
          {gap && <p className="subtle">What to provide: {gap.provide}</p>}
        </div>
        <p className="cta-row">
          <Link className="btn" to="/capture">Add a bill</Link>
        </p>
      </section>
    )
  }

  const costs = analysis.bundle.costs_by_flow_temp
  const gasFromBills = Boolean(analysis.bundle.measured)
  const breakEven = costs[0]?.break_even_flow_temp_c.central ?? 48
  const chartData = costs.map((c) => ({
    flow: c.design_flow_temp_c,
    savingCentral: c.annual_saving_gbp.central,
    savingLow: c.annual_saving_gbp.low,
    savingHigh: c.annual_saving_gbp.high,
    savingSpread: [
      c.annual_saving_gbp.central - c.annual_saving_gbp.low,
      c.annual_saving_gbp.high - c.annual_saving_gbp.central,
    ] as [number, number],
    positive: c.annual_saving_gbp.central >= 0,
  }))

  return (
    <section className="screen cost-screen">
      <h1>Costs</h1>
      {placeLabel && <p className="place-label">{placeLabel}</p>}
      {analysis.costs_annualised && <p className="card" role="status">Estimated annual Costs: gas usage is annualised using a full year of local weather. 12 months of usage in a row gives the best comparison.</p>}
      <p className="lede prose-measure">
        Annual saving vs gas at the price cap — every bar is a range; central value shown.
      </p>

      <div className="break-even-callout prose-measure">
        Above about <strong>{breakEven.toFixed(0)} °C</strong> flow, the heat pump costs more than gas.
      </div>

      <div className="cost-layout">
        <div className="chart-wrap">
          <p className="chart-axis-caption">Annual saving vs gas (£/yr)</p>
          <ResponsiveContainer width="100%" height={280}>
            <BarChart data={chartData} margin={{ top: 20, right: 8, left: 8, bottom: 32 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
              <XAxis
                type="category"
                dataKey="flow"
                ticks={[40, 45, 50, 55]}
                tickFormatter={(v) => `${v} °C`}
              >
                <Label value="Flow temperature" position="bottom" offset={12} />
              </XAxis>
              <YAxis tickFormatter={(v) => formatGBP(Number(v))} width={80} />
              <Tooltip
                formatter={(value, _name, item) => {
                  const row = item.payload as (typeof chartData)[number]
                  return [
                    `${formatGBP(row.savingLow)} – ${formatGBP(row.savingHigh)} (central ${formatGBP(Number(value ?? 0))})`,
                    'Saving range',
                  ]
                }}
                labelFormatter={(l) => `Flow ${l} °C`}
              />
              <ReferenceLine y={0} stroke="var(--text-muted)" />
              <ReferenceLine
                x={breakEven}
                stroke="var(--color-fabric)"
                strokeWidth={3}
                strokeDasharray="6 4"
                label={{
                  value: `break-even ≈ ${breakEven.toFixed(0)} °C`,
                  position: 'top',
                  fill: 'var(--color-fabric)',
                  fontSize: 16,
                  fontWeight: 600,
                }}
              />
              <Bar dataKey="savingCentral" radius={[4, 4, 0, 0]}>
                <ErrorBar dataKey="savingSpread" width={4} stroke="var(--ink)" />
                {chartData.map((entry) => (
                  <Cell key={entry.flow} fill={entry.positive ? 'var(--color-ok)' : 'var(--color-warn)'} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>

        <ul className="cost-table">
          {costs.map((c) => (
            <li key={c.design_flow_temp_c} className="card">
              <h3>{c.design_flow_temp_c} °C flow</h3>
              <p>
                Gas: <strong>{formatGBP(c.gas_cost_gbp.value)}</strong>{' '}
                {analysis.costs_annualised ? <span className="subtle">estimated annual gas</span> : gasFromBills ? (
                  <span className="conf conf-high">known from bills</span>
                ) : (
                  <span className="subtle">illustrative only</span>
                )}
              </p>
              <p>
                Heat pump: <RangeValue range={c.heat_pump_cost_gbp} unit="/yr" money decimals={0} />
              </p>
              <p>
                Saving: <RangeValue range={c.annual_saving_gbp} unit="/yr" money decimals={0} />
              </p>
            </li>
          ))}
        </ul>
      </div>

    </section>
  )
}
