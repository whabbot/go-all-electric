import { Link } from 'react-router-dom'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { useSession } from '../context/SessionContext'
import { RangeValue } from '../components/RangeValue'

export function CostScreen() {
  const { analysis } = useSession()
  if (!analysis) {
    return (
      <p className="warning">
        Run <Link to="/estimates">estimates</Link> first.
      </p>
    )
  }

  const costs = analysis.costs_by_flow_temp
  const breakEven = costs[0]?.break_even_flow_temp_c.central ?? 48
  const chartData = costs.map((c) => ({
    flow: c.design_flow_temp_c,
    savingCentral: c.annual_saving_gbp.central,
    savingLow: c.annual_saving_gbp.low,
    savingHigh: c.annual_saving_gbp.high,
    positive: c.annual_saving_gbp.central >= 0,
  }))

  return (
    <section className="screen cost-screen">
      <h1>Will it be cheaper?</h1>
      <p className="lede">
        Annual saving vs gas at the price cap — every bar is a range; central value shown.
      </p>

      <div className="break-even-callout">
        Above about <strong>{breakEven.toFixed(0)} °C</strong> flow, the heat pump costs more than gas.
      </div>

      <div className="chart-wrap">
        <ResponsiveContainer width="100%" height={280}>
          <BarChart data={chartData} margin={{ top: 12, right: 8, left: 0, bottom: 8 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
            <XAxis dataKey="flow" tickFormatter={(v) => `${v}°C`} />
            <YAxis tickFormatter={(v) => `£${v}`} />
            <Tooltip
              formatter={(value) => [`£${Number(value ?? 0).toFixed(0)}`, 'Central saving']}
              labelFormatter={(l) => `Flow ${l}°C`}
            />
            <ReferenceLine y={0} stroke="var(--text-muted)" />
            <ReferenceLine x={breakEven} stroke="var(--color-accent)" strokeDasharray="4 4" label="Break-even" />
            <Bar dataKey="savingCentral" radius={[4, 4, 0, 0]}>
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
              Gas: <strong>£{c.gas_cost_gbp.value.toFixed(0)}</strong>{' '}
              <span className="conf conf-high">known from bills</span>
            </p>
            <p>
              Heat pump: <RangeValue range={c.heat_pump_cost_gbp} unit=" £/yr" decimals={0} />
            </p>
            <p>
              Saving: <RangeValue range={c.annual_saving_gbp} unit=" £/yr" decimals={0} />
            </p>
          </li>
        ))}
      </ul>

      <p className="cta-row">
        <Link className="btn primary" to="/spec">Target installation</Link>
      </p>
    </section>
  )
}
