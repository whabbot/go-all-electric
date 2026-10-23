import { useCallback, useEffect, useRef, useState } from 'react'

export type ImageRect = { x: number; y: number; w: number; h: number }

type Props = {
  imageUrl: string
  title: string
  guidance?: string
  fileName: string
  onConfirm: (file: File) => void
  onCancel: () => void
}

type Mode = 'redact' | 'crop'

function clampRect(r: ImageRect, maxW: number, maxH: number): ImageRect {
  const x = Math.max(0, Math.min(r.x, maxW - 1))
  const y = Math.max(0, Math.min(r.y, maxH - 1))
  const w = Math.max(4, Math.min(r.w, maxW - x))
  const h = Math.max(4, Math.min(r.h, maxH - y))
  return { x, y, w, h }
}

async function exportRedacted(
  img: HTMLImageElement,
  redacts: ImageRect[],
  crop: ImageRect | null,
  fileName: string,
): Promise<File> {
  const source = crop ?? { x: 0, y: 0, w: img.naturalWidth, h: img.naturalHeight }
  const canvas = document.createElement('canvas')
  canvas.width = source.w
  canvas.height = source.h
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('Canvas not available')
  ctx.drawImage(img, source.x, source.y, source.w, source.h, 0, 0, source.w, source.h)
  ctx.fillStyle = '#000'
  for (const box of redacts) {
    const bx = box.x - source.x
    const by = box.y - source.y
    if (bx + box.w < 0 || by + box.h < 0 || bx > source.w || by > source.h) continue
    ctx.fillRect(bx, by, box.w, box.h)
  }
  const blob = await new Promise<Blob>((resolve, reject) => {
    canvas.toBlob(
      (b) => (b ? resolve(b) : reject(new Error('JPEG encode failed'))),
      'image/jpeg',
      0.9,
    )
  })
  const safe = fileName.replace(/\.[^.]+$/, '') || 'upload'
  return new File([blob], `${safe}-redacted.jpg`, { type: 'image/jpeg', lastModified: Date.now() })
}

export function ImageCoverUp({ imageUrl, title, guidance, fileName, onConfirm, onCancel }: Props) {
  const wrapRef = useRef<HTMLDivElement>(null)
  const [wrapWidth, setWrapWidth] = useState(320)
  const [img, setImg] = useState<HTMLImageElement | null>(null)
  const [mode, setMode] = useState<Mode>('redact')
  const [redacts, setRedacts] = useState<ImageRect[]>([])
  const [crop, setCrop] = useState<ImageRect | null>(null)
  const [draft, setDraft] = useState<ImageRect | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    const el = new Image()
    el.onload = () => setImg(el)
    el.src = imageUrl
    return () => {
      el.onload = null
    }
  }, [imageUrl])

  useEffect(() => {
    const el = wrapRef.current
    if (!el) return
    const ro = new ResizeObserver(() => setWrapWidth(el.clientWidth))
    ro.observe(el)
    setWrapWidth(el.clientWidth)
    return () => ro.disconnect()
  }, [])

  const layout = useCallback(() => {
    const wrap = wrapRef.current
    if (!wrap || !img) return null
    const cw = wrap.clientWidth
    const ch = Math.min(420, window.innerHeight * 0.45)
    const scale = Math.min(cw / img.naturalWidth, ch / img.naturalHeight)
    const dw = img.naturalWidth * scale
    const dh = img.naturalHeight * scale
    const ox = (cw - dw) / 2
    const oy = (ch - dh) / 2
    return { scale, ox, oy, dw, dh, ch }
  }, [img])

  const toImageCoords = (clientX: number, clientY: number): { x: number; y: number } | null => {
    const wrap = wrapRef.current
    const L = layout()
    if (!wrap || !L || !img) return null
    const rect = wrap.getBoundingClientRect()
    const x = (clientX - rect.left - L.ox) / L.scale
    const y = (clientY - rect.top - L.oy) / L.scale
    if (x < 0 || y < 0 || x > img.naturalWidth || y > img.naturalHeight) return null
    return { x, y }
  }

  const onPointerDown = (e: React.PointerEvent) => {
    if (!img) return
    const pt = toImageCoords(e.clientX, e.clientY)
    if (!pt) return
    e.currentTarget.setPointerCapture(e.pointerId)
    setDraft({ x: pt.x, y: pt.y, w: 0, h: 0 })
  }

  const onPointerMove = (e: React.PointerEvent) => {
    if (!draft || !img) return
    const pt = toImageCoords(e.clientX, e.clientY)
    if (!pt) return
    const x = Math.min(draft.x, pt.x)
    const y = Math.min(draft.y, pt.y)
    const w = Math.abs(pt.x - draft.x)
    const h = Math.abs(pt.y - draft.y)
    setDraft(clampRect({ x, y, w, h }, img.naturalWidth, img.naturalHeight))
  }

  const onPointerUp = () => {
    if (!draft || !img) return
    if (draft.w < 8 || draft.h < 8) {
      setDraft(null)
      return
    }
    if (mode === 'redact') {
      setRedacts((prev) => [...prev, draft])
    } else {
      setCrop(clampRect(draft, img.naturalWidth, img.naturalHeight))
    }
    setDraft(null)
  }

  const confirm = async () => {
    if (!img) return
    setBusy(true)
    try {
      const file = await exportRedacted(img, redacts, crop, fileName)
      onConfirm(file)
    } finally {
      setBusy(false)
    }
  }

  const L = layout()

  return (
    <div className="cover-up-overlay" role="dialog" aria-modal="true" aria-labelledby="cover-up-title">
      <div className="cover-up-panel card">
        <h2 id="cover-up-title">{title}</h2>
        <p className="cover-up-sent-label">Preview — exactly what will be sent</p>
        {guidance && <p className="cover-up-guidance">{guidance}</p>}

        <div
          ref={wrapRef}
          className="cover-up-canvas-wrap"
          style={L ? { minHeight: L.ch } : undefined}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerCancel={onPointerUp}
        >
          {img && L && (
            <>
              <img
                src={imageUrl}
                alt=""
                className="cover-up-image"
                style={{
                  width: L.dw,
                  height: L.dh,
                  left: L.ox,
                  top: L.oy,
                }}
                draggable={false}
              />
              <svg className="cover-up-svg" width={wrapWidth} height={L.ch} aria-hidden>
                {crop && (
                  <rect
                    x={L.ox + crop.x * L.scale}
                    y={L.oy + crop.y * L.scale}
                    width={crop.w * L.scale}
                    height={crop.h * L.scale}
                    fill="none"
                    stroke="var(--color-accent)"
                    strokeWidth={2}
                    strokeDasharray="6 4"
                  />
                )}
                {redacts.map((r, i) => (
                  <rect
                    key={i}
                    x={L.ox + r.x * L.scale}
                    y={L.oy + r.y * L.scale}
                    width={r.w * L.scale}
                    height={r.h * L.scale}
                    fill="#000"
                  />
                ))}
                {draft && (
                  <rect
                    x={L.ox + draft.x * L.scale}
                    y={L.oy + draft.y * L.scale}
                    width={draft.w * L.scale}
                    height={draft.h * L.scale}
                    fill={mode === 'redact' ? '#000' : 'none'}
                    stroke={mode === 'crop' ? 'var(--color-accent)' : undefined}
                    strokeWidth={2}
                    opacity={mode === 'redact' ? 0.85 : 1}
                  />
                )}
              </svg>
            </>
          )}
        </div>

        <div className="cover-up-tools">
          <button
            type="button"
            className={`btn ${mode === 'redact' ? 'primary' : ''}`}
            onClick={() => setMode('redact')}
          >
            Black out
          </button>
          <button
            type="button"
            className={`btn ${mode === 'crop' ? 'primary' : ''}`}
            onClick={() => setMode('crop')}
          >
            Crop
          </button>
          <button
            type="button"
            className="btn"
            disabled={redacts.length === 0}
            onClick={() => setRedacts((prev) => prev.slice(0, -1))}
          >
            Undo box
          </button>
          <button type="button" className="btn" disabled={!crop} onClick={() => setCrop(null)}>
            Clear crop
          </button>
        </div>

        <p className="cover-up-hint">
          Drag on the image to {mode === 'redact' ? 'draw opaque black boxes' : 'select a crop area'}.
          Touch works on your phone.
        </p>

        <div className="cover-up-actions">
          <button type="button" className="btn" onClick={onCancel} disabled={busy}>
            Cancel
          </button>
          <button type="button" className="btn primary" onClick={() => void confirm()} disabled={!img || busy}>
            {busy ? 'Preparing…' : 'Send this image'}
          </button>
        </div>
      </div>
    </div>
  )
}
