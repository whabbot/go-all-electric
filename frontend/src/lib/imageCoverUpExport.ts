import type { ImageRect } from './imageCoverUpGeometry'

export async function exportCoverUpImage(
  img: HTMLImageElement,
  redacts: ImageRect[],
  fileName: string,
): Promise<File> {
  const w = img.naturalWidth
  const h = img.naturalHeight
  const canvas = document.createElement('canvas')
  canvas.width = w
  canvas.height = h
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('Canvas not available')
  ctx.drawImage(img, 0, 0)
  ctx.fillStyle = '#000'
  for (const box of redacts) {
    ctx.fillRect(box.x, box.y, box.w, box.h)
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

export async function rasterizeCropRegion(
  img: HTMLImageElement,
  crop: ImageRect,
): Promise<{ url: string; width: number; height: number }> {
  const canvas = document.createElement('canvas')
  canvas.width = crop.w
  canvas.height = crop.h
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('Canvas not available')
  ctx.drawImage(img, crop.x, crop.y, crop.w, crop.h, 0, 0, crop.w, crop.h)
  const blob = await new Promise<Blob>((resolve, reject) => {
    canvas.toBlob(
      (b) => (b ? resolve(b) : reject(new Error('JPEG encode failed'))),
      'image/jpeg',
      0.92,
    )
  })
  return { url: URL.createObjectURL(blob), width: crop.w, height: crop.h }
}
