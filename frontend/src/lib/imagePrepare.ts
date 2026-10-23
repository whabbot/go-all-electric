/** Re-encode images in-browser: respect orientation, drop EXIF, cap size for upload speed. */

const MAX_EDGE_PX = 2048
const JPEG_QUALITY = 0.88

export async function prepareImageFile(file: File): Promise<File> {
  const bitmap = await createImageBitmap(file, { imageOrientation: 'from-image' })
  const scale = Math.min(1, MAX_EDGE_PX / Math.max(bitmap.width, bitmap.height))
  const w = Math.max(1, Math.round(bitmap.width * scale))
  const h = Math.max(1, Math.round(bitmap.height * scale))
  const canvas = document.createElement('canvas')
  canvas.width = w
  canvas.height = h
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('Canvas not available')
  ctx.drawImage(bitmap, 0, 0, w, h)
  bitmap.close()

  const blob = await new Promise<Blob>((resolve, reject) => {
    canvas.toBlob(
      (b) => (b ? resolve(b) : reject(new Error('JPEG encode failed'))),
      'image/jpeg',
      JPEG_QUALITY,
    )
  })

  const base = file.name.replace(/\.[^.]+$/, '') || 'photo'
  return new File([blob], `${base}-prepared.jpg`, { type: 'image/jpeg', lastModified: Date.now() })
}
