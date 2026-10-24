const gbpFormatter = new Intl.NumberFormat('en-GB', {
  style: 'currency',
  currency: 'GBP',
  maximumFractionDigits: 0,
})

/** en-GB money with thousands separators and a true minus sign (−). */
export function formatGBP(value: number): string {
  if (value < 0) {
    return `−${gbpFormatter.format(-value)}`
  }
  return gbpFormatter.format(value)
}

/** Axis / compact money without the £ prefix (chart ticks). */
export function formatGBPAxis(value: number): string {
  const abs = Math.abs(value)
  const formatted = new Intl.NumberFormat('en-GB', { maximumFractionDigits: 0 }).format(abs)
  return value < 0 ? `−${formatted}` : formatted
}

export function formatTempC(c: number): string {
  return `${c} °C`
}

export function formatKwRange(low: number, high: number): string {
  return `${low}–${high} kW`
}

/** Low – central – high with en-GB currency formatting. */
export function formatGBPRange(low: number, central: number, high: number, suffix = ''): string {
  return `${formatGBP(low)}–${formatGBP(central)}–${formatGBP(high)}${suffix}`
}
