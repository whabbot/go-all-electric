import { describe, expect, it } from 'vitest'
import {
  clampRect,
  hitTestCrop,
  moveCrop,
  resizeCropByHandle,
  transformRedactsForCrop,
} from './imageCoverUpGeometry'

describe('imageCoverUpGeometry', () => {
  it('clamps crop rectangles inside the image', () => {
    expect(clampRect({ x: -5, y: 0, w: 200, h: 100 }, 400, 300)).toMatchObject({
      x: 0,
      w: 200,
    })
  })

  it('detects corner handles', () => {
    const crop = { x: 50, y: 50, w: 100, h: 80 }
    expect(hitTestCrop(crop, 50, 50, 400, 300)).toBe('nw')
    expect(hitTestCrop(crop, 150, 130, 400, 300)).toBe('se')
  })

  it('resizes from the east handle', () => {
    const crop = { x: 10, y: 10, w: 50, h: 40 }
    const next = resizeCropByHandle(crop, 'e', 80, 30, 200, 200)
    expect(next.w).toBeGreaterThan(crop.w)
  })

  it('moves crop without changing size', () => {
    const crop = { x: 10, y: 10, w: 50, h: 40 }
    const moved = moveCrop(crop, 5, 5, 200, 200)
    expect(moved).toEqual({ x: 15, y: 15, w: 50, h: 40 })
  })

  it('transforms redact boxes into cropped coordinates', () => {
    const crop = { x: 20, y: 10, w: 60, h: 50 }
    const redacts = [
      { x: 30, y: 20, w: 20, h: 15 },
      { x: 0, y: 0, w: 10, h: 10 },
    ]
    expect(transformRedactsForCrop(redacts, crop)).toEqual([{ x: 10, y: 10, w: 20, h: 15 }])
  })
})
