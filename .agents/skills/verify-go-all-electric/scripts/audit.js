() => {
  // Go All-Electric UI audit. Paste into: chrome-devtools-axi eval "$(cat audit.js)"
  // Audits the app inside the __frame.html harness iframe when present, else the top page.
  const frame = document.getElementById('f')
  const win = frame ? frame.contentWindow : window
  const doc = win.document
  const vw = win.innerWidth, vh = win.innerHeight

  const cv = document.createElement('canvas'); cv.width = cv.height = 1
  const cx = cv.getContext('2d', { willReadFrequently: true })
  const rgba = (css) => {
    cx.clearRect(0, 0, 1, 1); cx.fillStyle = '#000'; cx.fillStyle = css; cx.fillRect(0, 0, 1, 1)
    const [r, g, b, a] = cx.getImageData(0, 0, 1, 1).data
    return [r, g, b, a / 255]
  }
  const over = (top, under) => {
    const a = top[3]
    return [0, 1, 2].map((i) => top[i] * a + under[i] * (1 - a)).concat(1)
  }
  const lum = ([r, g, b]) => {
    const c = [r, g, b].map((v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4 })
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
  }
  const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05) }
  const bgOf = (el) => {
    const layers = []
    for (let n = el; n && n.nodeType === 1; n = n.parentElement) {
      const c = rgba(win.getComputedStyle(n).backgroundColor)
      if (c[3] > 0) layers.push(c)
      if (c[3] >= 1) break
    }
    let base = [255, 255, 255, 1]
    for (let i = layers.length - 1; i >= 0; i--) base = over(layers[i], base)
    return base
  }
  const opacityOf = (el) => { let o = 1; for (let n = el; n && n.nodeType === 1; n = n.parentElement) o *= parseFloat(win.getComputedStyle(n).opacity); return o }
  const visible = (el) => {
    const r = el.getBoundingClientRect(), s = win.getComputedStyle(el)
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'
  }
  const label = (el) => (el.getAttribute('aria-label') || el.textContent || el.value || el.tagName).trim().replace(/\s+/g, ' ').slice(0, 40)
  const disabled = (el) => el.closest('button:disabled, .btn.disabled, [aria-disabled="true"]')

  // Text: every visible element with its own text.
  const texts = []
  for (const el of doc.body.querySelectorAll('*')) {
    if (['SCRIPT', 'STYLE', 'svg', 'SVG'].includes(el.tagName) || el.closest('svg')) continue
    const own = [...el.childNodes].filter((n) => n.nodeType === 3).map((n) => n.textContent).join('').trim()
    if (!own || !visible(el)) continue
    const s = win.getComputedStyle(el)
    const size = parseFloat(s.fontSize), weight = parseInt(s.fontWeight, 10)
    const bg = bgOf(el)
    let fg = rgba(s.color)
    fg = over([fg[0], fg[1], fg[2], fg[3] * opacityOf(el)], bg)
    const large = size >= 24 || (size >= 18.66 && weight >= 700)
    texts.push({ el, own, size, weight, cr: ratio(fg, bg), need: large ? 3 : 4.5, dis: Boolean(disabled(el)) })
  }
  const chars = texts.reduce((n, t) => n + t.own.length, 0)
  const pctBelow = (px) => Math.round(100 * texts.filter((t) => t.size < px).reduce((n, t) => n + t.own.length, 0) / Math.max(chars, 1))
  const sizes = {}
  for (const t of texts) sizes[t.size] = (sizes[t.size] || 0) + t.own.length
  const contrastFails = texts.filter((t) => !t.dis && t.cr < t.need)
    .map((t) => `${t.cr.toFixed(2)}<${t.need} ${t.size}px "${t.own.slice(0, 32)}"`)

  // Body copy line length (characters per line) for paragraphs and list items.
  const cpl = []
  for (const el of doc.querySelectorAll('p, li')) {
    if (!visible(el)) continue
    const s = win.getComputedStyle(el), txt = el.textContent.trim()
    if (txt.length < 80) continue
    cx.font = `${s.fontWeight} ${s.fontSize} ${s.fontFamily}`
    const avg = cx.measureText(txt).width / txt.length
    cpl.push(Math.round(el.getBoundingClientRect().width / avg))
  }

  // Tap targets (WCAG 2.5.5 AAA / Apple HIG 44px).
  const targets = [...doc.querySelectorAll('a[href], button, input:not([type=hidden]), select, textarea, label.upload-btn, summary, [role=button], [tabindex]:not([tabindex="-1"])')]
    .filter((el) => visible(el) || el.closest('label.upload-btn'))
    .map((el) => (el.tagName === 'INPUT' && el.type === 'file' ? el.closest('label') || el : el))
    .filter((el, i, a) => a.indexOf(el) === i && visible(el))
  const small = targets.filter((el) => { const r = el.getBoundingClientRect(); return r.height < 44 || r.width < 44 })
    .map((el) => { const r = el.getBoundingClientRect(); return `${Math.round(r.width)}x${Math.round(r.height)} ${el.tagName.toLowerCase()} "${label(el)}"` })

  // Focus styles authored in CSS (the UA ring alone scores at most 3).
  let focusRules = 0
  for (const sh of doc.styleSheets) { try { for (const r of sh.cssRules) if (/:focus/.test(r.selectorText || '')) focusRules++ } catch { /* cross-origin */ } }

  // Palette, type scale and component variety.
  const colors = new Set(), radii = new Set(), btnH = new Set(), families = new Set()
  for (const el of doc.body.querySelectorAll('*')) {
    if (!visible(el)) continue
    const s = win.getComputedStyle(el)
    families.add(s.fontFamily.split(',')[0].trim())
    if (rgba(s.backgroundColor)[3] > 0) colors.add(s.backgroundColor)
    colors.add(s.color)
    if (parseFloat(s.borderTopLeftRadius) > 0) radii.add(s.borderTopLeftRadius)
  }
  for (const el of doc.querySelectorAll('button, .btn, label.upload-btn')) if (visible(el)) btnH.add(Math.round(el.getBoundingClientRect().height))

  const main = doc.querySelector('main') || doc.body
  const mr = main.getBoundingClientRect()
  const h1 = doc.querySelector('h1')
  const kw = [...doc.querySelectorAll('.kw-display, [data-hero]')].filter(visible)
    .map((el) => { const r = el.getBoundingClientRect(); return `${parseFloat(win.getComputedStyle(el).fontSize)}px bottom=${Math.round(r.bottom)}` })

  return {
    viewport: `${vw}x${vh}`, path: win.location.pathname,
    hOverflow: doc.documentElement.scrollWidth > vw, pageHeight: doc.documentElement.scrollHeight,
    mainWidthPct: Math.round(100 * mr.width / vw),
    h1: h1 ? `${parseFloat(win.getComputedStyle(h1).fontSize)}px "${h1.textContent.trim().slice(0, 40)}"` : null,
    bodyFont: win.getComputedStyle(doc.body).fontSize, fontFamilies: [...families],
    minTextPx: Math.min(...texts.map((t) => t.size)),
    pctCharsBelow14: pctBelow(14), pctCharsBelow16: pctBelow(16), pctCharsBelow18: pctBelow(18),
    fontSizesByChars: Object.entries(sizes).sort((a, b) => b[1] - a[1]).map(([k, v]) => `${k}px:${v}`).join(' '),
    contrastFails: contrastFails.length, contrastSamples: contrastFails.slice(0, 8),
    minContrast: Math.min(...texts.filter((t) => !t.dis).map((t) => t.cr)).toFixed(2),
    cplMedian: cpl.sort((a, b) => a - b)[Math.floor(cpl.length / 2)] ?? null, cplMax: cpl.length ? Math.max(...cpl) : null,
    targets: targets.length, smallTargets: small.length, smallSamples: small.slice(0, 10),
    focusRules, distinctColors: colors.size, distinctRadii: [...radii].join(' '), buttonHeights: [...btnH].sort((a, b) => a - b).join(' '),
    heroKw: kw,
  }
}
