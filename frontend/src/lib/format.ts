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
  if (low < 0 || central < 0 || high < 0) {
    return formatSignedMoneyRange(low, central, high, suffix)
  }
  return `${formatGBP(low)}–${formatGBP(central)}–${formatGBP(high)}${suffix}`
}

/** Annual saving ranges that cross zero — costs vs savings in plain language. */
export function formatSignedMoneyRange(
  low: number,
  central: number,
  high: number,
  suffix = '',
): string {
  const fmtDelta = (value: number) => {
    const abs = formatGBP(Math.abs(value))
    if (value > 0) return `${abs} saving`
    if (value < 0) return `${abs} more`
    return 'no change'
  }
  const centralPhrase = `about ${fmtDelta(central)}`
  if (low === high) return `${centralPhrase}${suffix}`
  return `${centralPhrase}${suffix} (range ${fmtDelta(low)} to ${fmtDelta(high)})`
}
