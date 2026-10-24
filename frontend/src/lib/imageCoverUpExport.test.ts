import { describe, expect, it, vi } from 'vitest'
import { exportCoverUpImage, rasterizeCropRegion } from './imageCoverUpExport'

describe('imageCoverUpExport', () => {
  it('rasterizes a crop to the selection size', async () => {
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({
      drawImage: vi.fn(),
    } as unknown as CanvasRenderingContext2D)
    vi.spyOn(HTMLCanvasElement.prototype, 'toBlob').mockImplementation(function mockToBlob(
      this: HTMLCanvasElement,
      cb: BlobCallback,
    ) {
      cb(new Blob(['jpeg'], { type: 'image/jpeg' }))
    })
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:test-crop')

    const img = {
      naturalWidth: 100,
      naturalHeight: 80,
    } as HTMLImageElement

    const out = await rasterizeCropRegion(img, { x: 10, y: 5, w: 40, h: 30 })
    expect(out.width).toBe(40)
    expect(out.height).toBe(30)
    expect(out.url).toBe('blob:test-crop')
  })

  it('exports redacted JPEG at the current image size', async () => {
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({
      drawImage: vi.fn(),
      fillRect: vi.fn(),
    } as unknown as CanvasRenderingContext2D)
    vi.spyOn(HTMLCanvasElement.prototype, 'toBlob').mockImplementation(function mockToBlob(
      _cb: BlobCallback,
    ) {
      _cb(new Blob(['jpeg'], { type: 'image/jpeg' }))
    })

    const img = { naturalWidth: 50, naturalHeight: 40 } as HTMLImageElement
    const file = await exportCoverUpImage(img, [{ x: 1, y: 2, w: 10, h: 8 }], 'shot.png')
    expect(file.name).toBe('shot-redacted.jpg')
    expect(file.type).toBe('image/jpeg')
  })
})
