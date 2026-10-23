import * as pdfjs from 'pdfjs-dist'

pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  'pdfjs-dist/build/pdf.worker.min.mjs',
  import.meta.url,
).toString()

const MAX_PAGES_PER_PDF = 12
const RENDER_SCALE = 1.5

export async function pdfFileToPageImages(file: File): Promise<File[]> {
  const data = await file.arrayBuffer()
  const doc = await pdfjs.getDocument({ data }).promise
  const pageCount = Math.min(doc.numPages, MAX_PAGES_PER_PDF)
  const base = file.name.replace(/\.pdf$/i, '') || 'quote'
  const out: File[] = []

  for (let pageNum = 1; pageNum <= pageCount; pageNum += 1) {
    const page = await doc.getPage(pageNum)
    const viewport = page.getViewport({ scale: RENDER_SCALE })
    const canvas = document.createElement('canvas')
    canvas.width = viewport.width
    canvas.height = viewport.height
    const ctx = canvas.getContext('2d')
    if (!ctx) throw new Error('Canvas not available')
    await page.render({ canvas, canvasContext: ctx, viewport }).promise
    const blob = await new Promise<Blob>((resolve, reject) => {
      canvas.toBlob(
        (b) => (b ? resolve(b) : reject(new Error('JPEG encode failed'))),
        'image/jpeg',
        0.9,
      )
    })
    out.push(
      new File([blob], `${base}-p${pageNum}.jpg`, {
        type: 'image/jpeg',
        lastModified: Date.now(),
      }),
    )
  }

  return out
}
