import { describe, expect, it } from 'vitest'
import type { PhotoKind } from '../api'
import { firstCaptureSlotNeedingAttention } from './captureGuide'

const emptyPhotos = (kinds: PhotoKind[]) =>
  kinds.map((kind) => ({ kind, fileName: null as string | null }))

describe('firstCaptureSlotNeedingAttention', () => {
  it('returns gas bill when nothing is uploaded', () => {
    const kinds: PhotoKind[] = [
      'gas_bill',
      'loft',
      'boiler_plate',
      'radiators',
      'fuse_cutout',
      'outdoor_space',
    ]
    expect(firstCaptureSlotNeedingAttention(emptyPhotos(kinds), null)).toBe('gas_bill')
  })

  it('returns loft after gas bill is ready', () => {
    const photos = emptyPhotos([
      'gas_bill',
      'loft',
      'boiler_plate',
      'radiators',
      'fuse_cutout',
      'outdoor_space',
    ])
    photos[0].fileName = 'bill.jpg'
    expect(firstCaptureSlotNeedingAttention(photos, null)).toBe('loft')
  })

  it('treats radiator video as satisfying the radiators slot', () => {
    const photos = emptyPhotos([
      'gas_bill',
      'loft',
      'boiler_plate',
      'radiators',
      'fuse_cutout',
      'outdoor_space',
    ])
    photos.forEach((p) => {
      p.fileName = 'x.jpg'
    })
    photos[3].fileName = null
    const video = new File(['v'], 'r.mp4', { type: 'video/mp4' })
    expect(firstCaptureSlotNeedingAttention(photos, video)).toBe(null)
  })
})
