import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { PhotoKind } from '../api'
import { CAPTURE_GUIDANCE } from '../lib/captureGuide'
import { CaptureExamplesDialog } from './CaptureExamplesDialog'

afterEach(cleanup)

describe('CaptureExamplesDialog photos', () => {
  it.each(Object.keys(CAPTURE_GUIDANCE) as PhotoKind[])('shows fictional Good and Avoid photos for %s', (kind) => {
    render(<CaptureExamplesDialog kind={kind} title={kind} onClose={vi.fn()} returnFocusTo={null} />)
    const photos = screen.getAllByRole('img')
    expect(photos).toHaveLength(2)
    for (const photo of photos) {
      expect(photo).toHaveAttribute('loading', 'lazy')
      expect(photo).toHaveAttribute('decoding', 'async')
      expect(photo.getAttribute('alt')?.length).toBeGreaterThan(30)
      expect(photo.getAttribute('src')).toMatch(/\.webp$/)
    }
    expect(photos[0].getAttribute('src')).toContain('-good.webp')
    expect(photos[1].getAttribute('src')).toContain('-bad.webp')
    expect(screen.getByText(CAPTURE_GUIDANCE[kind].goodReason, { exact: false })).toBeInTheDocument()
    expect(screen.getByText(CAPTURE_GUIDANCE[kind].badReason, { exact: false })).toBeInTheDocument()
    expect(screen.getAllByText('Illustration · fictional example')).toHaveLength(2)
  })
})
