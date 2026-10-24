import { useCallback, useEffect, useId, useRef, useState } from 'react'
import {
  clampRect,
  hitTestCrop,
  moveCrop,
  resizeCropByHandle,
  transformRedactsForCrop,
  transformRedactsFromCropToOriginal,
  type CropHandle,
  type ImageRect,
} from '../lib/imageCoverUpGeometry'
import { exportCoverUpImage, rasterizeCropRegion } from '../lib/imageCoverUpExport'

export type { ImageRect }

type Props = {
  imageUrl: string
  title: string
  guidance?: string
  fileName: string
  /** e.g. "Photo 2 of 3" when several uploads are queued */
  progressLabel?: string
  onConfirm: (file: File) => void
  /** Skips this photo (the only one, or the current one of a batch). Escape does the same. */
  onCancel: () => void
  /** When more photos are queued: drops this one and every photo still waiting. */
  onCancelAll?: () => void
}

type DrawMode = 'crop' | 'redact'

type DragState =
  | { kind: 'new'; originX: number; originY: number }
  | { kind: 'resize'; handle: CropHandle; startCrop: ImageRect }
  | { kind: 'move'; startCrop: ImageRect; originX: number; originY: number }

export function ImageCoverUp({
  imageUrl,
  title,
  guidance,
  fileName,
  progressLabel,
  onConfirm,
  onCancel,
  onCancelAll,
}: Props) {
  const maskId = useId().replace(/:/g, '')
  const wrapRef = useRef<HTMLDivElement>(null)
  const derivedUrlRef = useRef<string | null>(null)
  const redactsBeforeCropRef = useRef<ImageRect[] | null>(null)
  const appliedCropRef = useRef<ImageRect | null>(null)
  const originalImageSizeRef = useRef<{ w: number; h: number } | null>(null)
  const [wrapWidth, setWrapWidth] = useState(320)
  const [displayUrl, setDisplayUrl] = useState(imageUrl)
  const [img, setImg] = useState<HTMLImageElement | null>(null)
  const [cropApplied, setCropApplied] = useState(false)
  const [drawMode, setDrawMode] = useState<DrawMode>('crop')
  const [cropSelection, setCropSelection] = useState<ImageRect | null>(null)
  const [redacts, setRedacts] = useState<ImageRect[]>([])
  const [draft, setDraft] = useState<ImageRect | null>(null)
  const [drag, setDrag] = useState<DragState | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !busy) {
        event.preventDefault()
        onCancel()
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [busy, onCancel])

  useEffect(() => {
    setDisplayUrl(imageUrl)
    setCropApplied(false)
    setCropSelection(null)
    setRedacts([])
    setDraft(null)
    setDrag(null)
    setDrawMode('crop')
  }, [imageUrl])

  useEffect(() => {
    const el = new Image()
    el.onload = () => setImg(el)
    el.src = displayUrl
    return () => {
      el.onload = null
    }
  }, [displayUrl])

  useEffect(() => {
    return () => {
      if (derivedUrlRef.current) {
        URL.revokeObjectURL(derivedUrlRef.current)
        derivedUrlRef.current = null
      }
    }
  }, [])

  useEffect(() => {
    const el = wrapRef.current
    if (!el) return
    const ro = new ResizeObserver(() => {
      const w = el.clientWidth
      if (w > 0) setWrapWidth(w)
    })
    ro.observe(el)
    if (el.clientWidth > 0) setWrapWidth(el.clientWidth)
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
    if (!img || busy) return
    const pt = toImageCoords(e.clientX, e.clientY)
    if (!pt) return
    e.currentTarget.setPointerCapture(e.pointerId)

    if (drawMode === 'redact') {
      setDraft({ x: pt.x, y: pt.y, w: 0, h: 0 })
      setDrag({ kind: 'new', originX: pt.x, originY: pt.y })
      return
    }

    if (cropApplied) return

    if (cropSelection) {
      const hit = hitTestCrop(cropSelection, pt.x, pt.y, img.naturalWidth, img.naturalHeight)
      if (hit === 'move') {
        setDrag({ kind: 'move', startCrop: cropSelection, originX: pt.x, originY: pt.y })
        return
      }
      if (hit !== 'new') {
        setDrag({ kind: 'resize', handle: hit, startCrop: cropSelection })
        return
      }
    }

    setDraft({ x: pt.x, y: pt.y, w: 0, h: 0 })
    setDrag({ kind: 'new', originX: pt.x, originY: pt.y })
  }

  const onPointerMove = (e: React.PointerEvent) => {
    if (!drag || !img) return
    const pt = toImageCoords(e.clientX, e.clientY)
    if (!pt) return

    if (drag.kind === 'new' && draft) {
      const x = Math.min(drag.originX, pt.x)
      const y = Math.min(drag.originY, pt.y)
      const w = Math.abs(pt.x - drag.originX)
      const h = Math.abs(pt.y - drag.originY)
      const next = clampRect({ x, y, w, h }, img.naturalWidth, img.naturalHeight)
      if (drawMode === 'redact') {
        setDraft(next)
      } else {
        setCropSelection(next)
        setDraft(next)
      }
      return
    }

    if (drag.kind === 'resize' && cropSelection) {
      setCropSelection(
        resizeCropByHandle(
          drag.startCrop,
          drag.handle,
          pt.x,
          pt.y,
          img.naturalWidth,
          img.naturalHeight,
        ),
      )
      return
    }

    if (drag.kind === 'move' && cropSelection) {
      const dx = pt.x - drag.originX
      const dy = pt.y - drag.originY
      setCropSelection(
        moveCrop(drag.startCrop, dx, dy, img.naturalWidth, img.naturalHeight),
      )
    }
  }

  const onPointerUp = () => {
    if (!drag || !img) return
    if (drawMode === 'redact' && draft) {
      if (draft.w >= 8 && draft.h >= 8) {
        setRedacts((prev) => [...prev, draft])
      }
      setDraft(null)
    } else if (drawMode === 'crop' && draft) {
      if (draft.w < 8 || draft.h < 8) {
        setCropSelection(null)
      }
      setDraft(null)
    }
    setDrag(null)
  }

  const applyCrop = async () => {
    if (!img || !cropSelection || cropApplied) return
    setBusy(true)
    try {
      const { url, width, height } = await rasterizeCropRegion(img, cropSelection)
      if (derivedUrlRef.current) URL.revokeObjectURL(derivedUrlRef.current)
      derivedUrlRef.current = url
      setDisplayUrl(url)
      redactsBeforeCropRef.current = redacts
      appliedCropRef.current = cropSelection
      originalImageSizeRef.current = { w: img.naturalWidth, h: img.naturalHeight }
      setCropApplied(true)
      setCropSelection(null)
      setRedacts(transformRedactsForCrop(redacts, cropSelection))
      setDrawMode('redact')
      const cropped = new Image()
      cropped.width = width
      cropped.height = height
      await new Promise<void>((resolve, reject) => {
        cropped.onload = () => resolve()
        cropped.onerror = () => reject(new Error('Crop preview failed'))
        cropped.src = url
      })
      setImg(cropped)
    } finally {
      setBusy(false)
    }
  }

  const undoCrop = () => {
    if (!cropApplied) return
    if (derivedUrlRef.current) {
      URL.revokeObjectURL(derivedUrlRef.current)
      derivedUrlRef.current = null
    }
    setDisplayUrl(imageUrl)
    setCropApplied(false)
    setCropSelection(null)
    const crop = appliedCropRef.current
    const size = originalImageSizeRef.current
    const before = redactsBeforeCropRef.current ?? []
    const afterCrop =
      crop && size
        ? transformRedactsFromCropToOriginal(redacts, crop, size.w, size.h)
        : redacts
    setRedacts([...before, ...afterCrop])
    redactsBeforeCropRef.current = null
    appliedCropRef.current = null
    originalImageSizeRef.current = null
    setDrawMode('crop')
    setImg(null)
  }

  const confirm = async () => {
    if (!img) return
    setBusy(true)
    try {
      const file = await exportCoverUpImage(img, redacts, fileName)
      onConfirm(file)
    } finally {
      setBusy(false)
    }
  }

  const L = layout()
  const canApplyCrop = Boolean(cropSelection && cropSelection.w >= 8 && cropSelection.h >= 8 && !cropApplied)

  const cropOverlay = cropSelection && L && !cropApplied

  return (
    <div className="cover-up-overlay" role="dialog" aria-modal="true" aria-labelledby="cover-up-title">
      <div className="cover-up-panel card">
        <h2 id="cover-up-title">{title}</h2>
        {progressLabel && <p className="cover-up-progress">{progressLabel}</p>}
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
                src={displayUrl}
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
                {cropOverlay && (
                  <>
                    <defs>
                      <mask id={maskId}>
                        <rect x={0} y={0} width={wrapWidth} height={L.ch} fill="white" />
                        <rect
                          x={L.ox + cropSelection.x * L.scale}
                          y={L.oy + cropSelection.y * L.scale}
                          width={cropSelection.w * L.scale}
                          height={cropSelection.h * L.scale}
                          fill="black"
                        />
                      </mask>
                    </defs>
                    <rect
                      x={0}
                      y={0}
                      width={wrapWidth}
                      height={L.ch}
                      fill="rgba(0,0,0,0.45)"
                      mask={`url(#${maskId})`}
                    />
                    <rect
                      x={L.ox + cropSelection.x * L.scale}
                      y={L.oy + cropSelection.y * L.scale}
                      width={cropSelection.w * L.scale}
                      height={cropSelection.h * L.scale}
                      fill="rgba(0,0,0,0)"
                      stroke="var(--color-accent)"
                      strokeWidth={2}
                    />
                    {(['nw', 'ne', 'se', 'sw'] as const).map((corner) => {
                      const cx =
                        corner.includes('e')
                          ? L.ox + (cropSelection.x + cropSelection.w) * L.scale
                          : L.ox + cropSelection.x * L.scale
                      const cy =
                        corner.includes('s')
                          ? L.oy + (cropSelection.y + cropSelection.h) * L.scale
                          : L.oy + cropSelection.y * L.scale
                      return (
                        <circle
                          key={corner}
                          cx={cx}
                          cy={cy}
                          r={6}
                          fill="var(--color-accent)"
                        />
                      )
                    })}
                  </>
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
                {drawMode === 'redact' && draft && (
                  <rect
                    x={L.ox + draft.x * L.scale}
                    y={L.oy + draft.y * L.scale}
                    width={draft.w * L.scale}
                    height={draft.h * L.scale}
                    fill="#000"
                    opacity={0.85}
                  />
                )}
              </svg>
            </>
          )}
        </div>

        <div className="cover-up-tools">
          <button
            type="button"
            className={`btn ${drawMode === 'crop' && !cropApplied ? 'primary' : ''}`}
            disabled={cropApplied}
            onClick={() => setDrawMode('crop')}
          >
            Crop area
          </button>
          <button
            type="button"
            className="btn"
            disabled={!canApplyCrop || busy}
            onClick={() => void applyCrop()}
          >
            {busy ? 'Cropping…' : 'Crop'}
          </button>
          <button type="button" className="btn" disabled={!cropApplied} onClick={undoCrop}>
            Undo crop
          </button>
          <button
            type="button"
            className={`btn ${drawMode === 'redact' ? 'primary' : ''}`}
            onClick={() => setDrawMode('redact')}
          >
            Black out
          </button>
          <button
            type="button"
            className="btn"
            disabled={redacts.length === 0}
            onClick={() => setRedacts((prev) => prev.slice(0, -1))}
          >
            Undo box
          </button>
        </div>

        <p className="cover-up-hint">
          {cropApplied
            ? 'Drag to draw black boxes over anything identifying. Touch works on your phone.'
            : drawMode === 'crop'
              ? 'Drag to select the area to keep, adjust the corners, then press Crop — the preview will shrink to that region.'
              : 'Switch to Crop area first, or apply a crop before blacking out.'}
        </p>

        <div className="cover-up-actions">
          {onCancelAll && (
            <button type="button" className="btn" onClick={onCancelAll} disabled={busy}>
              Cancel all
            </button>
          )}
          <button type="button" className="btn" onClick={onCancel} disabled={busy}>
            {onCancelAll ? 'Skip this photo' : 'Cancel'}
          </button>
          <button type="button" className="btn primary" onClick={() => void confirm()} disabled={!img || busy}>
            {busy ? 'Preparing…' : 'Use photo'}
          </button>
        </div>
      </div>
    </div>
  )
}
