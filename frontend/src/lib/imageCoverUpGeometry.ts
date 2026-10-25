export type ImageRect = { x: number; y: number; w: number; h: number }

export function clampRect(r: ImageRect, maxW: number, maxH: number): ImageRect {
  const x = Math.max(0, Math.min(r.x, maxW - 1))
  const y = Math.max(0, Math.min(r.y, maxH - 1))
  const w = Math.max(4, Math.min(r.w, maxW - x))
  const h = Math.max(4, Math.min(r.h, maxH - y))
  return { x, y, w, h }
}

export type CropHandle =
  | 'nw'
  | 'n'
  | 'ne'
  | 'e'
  | 'se'
  | 's'
  | 'sw'
  | 'w'
  | 'move'
  | 'new'

const HANDLE_HIT = 14

function dist(ax: number, ay: number, bx: number, by: number) {
  return Math.hypot(ax - bx, ay - by)
}

/** Hit test in image coordinates (same space as ImageRect). */
export function hitTestCrop(
  crop: ImageRect,
  x: number,
  y: number,
  maxW: number,
  maxH: number,
): CropHandle {
  const corners: { h: CropHandle; cx: number; cy: number }[] = [
    { h: 'nw', cx: crop.x, cy: crop.y },
    { h: 'ne', cx: crop.x + crop.w, cy: crop.y },
    { h: 'se', cx: crop.x + crop.w, cy: crop.y + crop.h },
    { h: 'sw', cx: crop.x, cy: crop.y + crop.h },
  ]
  for (const c of corners) {
    if (dist(x, y, c.cx, c.cy) <= HANDLE_HIT) return c.h
  }
  const mid: { h: CropHandle; cx: number; cy: number }[] = [
    { h: 'n', cx: crop.x + crop.w / 2, cy: crop.y },
    { h: 's', cx: crop.x + crop.w / 2, cy: crop.y + crop.h },
    { h: 'w', cx: crop.x, cy: crop.y + crop.h / 2 },
    { h: 'e', cx: crop.x + crop.w, cy: crop.y + crop.h / 2 },
  ]
  for (const m of mid) {
    if (dist(x, y, m.cx, m.cy) <= HANDLE_HIT) return m.h
  }
  if (x >= crop.x && x <= crop.x + crop.w && y >= crop.y && y <= crop.y + crop.h) return 'move'
  if (x >= 0 && x <= maxW && y >= 0 && y <= maxH) return 'new'
  return 'new'
}

export function resizeCropByHandle(
  crop: ImageRect,
  handle: CropHandle,
  anchorX: number,
  anchorY: number,
  maxW: number,
  maxH: number,
): ImageRect {
  if (handle === 'move') return crop
  let { x, y, w, h } = crop
  const right = x + w
  const bottom = y + h
  const px = anchorX
  const py = anchorY

  if (handle.includes('n')) {
    y = Math.min(py, bottom - 4)
    h = bottom - y
  }
  if (handle.includes('s')) {
    h = Math.max(4, py - y)
  }
  if (handle.includes('w')) {
    x = Math.min(px, right - 4)
    w = right - x
  }
  if (handle.includes('e')) {
    w = Math.max(4, px - x)
  }

  return clampRect({ x, y, w, h }, maxW, maxH)
}

export function moveCrop(crop: ImageRect, dx: number, dy: number, maxW: number, maxH: number): ImageRect {
  const x = Math.max(0, Math.min(crop.x + dx, maxW - crop.w))
  const y = Math.max(0, Math.min(crop.y + dy, maxH - crop.h))
  return { x, y, w: crop.w, h: crop.h }
}

const MIN_REDACT = 8

/** Clip redact boxes to the crop region and move them into cropped-image coordinates. */
export function transformRedactsFromCropToOriginal(
  redacts: ImageRect[],
  crop: ImageRect,
  maxW: number,
  maxH: number,
): ImageRect[] {
  const out: ImageRect[] = []
  for (const r of redacts) {
    out.push(
      clampRect({ x: r.x + crop.x, y: r.y + crop.y, w: r.w, h: r.h }, maxW, maxH),
    )
  }
  return out
}

export function transformRedactsForCrop(redacts: ImageRect[], crop: ImageRect): ImageRect[] {
  const out: ImageRect[] = []
  for (const r of redacts) {
    const ix = Math.max(r.x, crop.x)
    const iy = Math.max(r.y, crop.y)
    const ir = Math.min(r.x + r.w, crop.x + crop.w)
    const ib = Math.min(r.y + r.h, crop.y + crop.h)
    const w = ir - ix
    const h = ib - iy
    if (w >= MIN_REDACT && h >= MIN_REDACT) {
      out.push({ x: ix - crop.x, y: iy - crop.y, w, h })
    }
  }
  return out
}
