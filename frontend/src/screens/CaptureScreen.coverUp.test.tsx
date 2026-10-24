import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { SessionProvider } from '../context/SessionContext'
import { CaptureScreen } from './CaptureScreen'

vi.mock('../api/client', () => ({
  api: {
    checkPhoto: vi.fn().mockResolvedValue({
      kind: 'radiators',
      legible: true,
      matches_expected: true,
      summary: 'ok',
      model: 'test',
      elapsed_ms: 100,
    }),
    checkRadiatorVideo: vi.fn(),
  },
  isMockMode: () => true,
}))

vi.mock('../lib/imagePrepare', () => ({
  prepareImageFile: vi.fn(async (file: File) => file),
}))

vi.mock('../components/ImageCoverUp', () => ({
  ImageCoverUp: ({
    progressLabel,
    onCancel,
    onConfirm,
  }: {
    progressLabel?: string
    onCancel: () => void
    onConfirm: (f: File) => void
  }) => (
    <div role="dialog" aria-label="cover-up-mock">
      {progressLabel && <p>{progressLabel}</p>}
      <button type="button" onClick={onCancel}>Cancel</button>
      <button
        type="button"
        onClick={() => onConfirm(new File(['x'], 'redacted.jpg', { type: 'image/jpeg' }))}
      >
        Use photo
      </button>
    </div>
  ),
}))

function renderCapture() {
  return render(
    <SessionProvider>
      <MemoryRouter>
        <CaptureScreen />
      </MemoryRouter>
    </SessionProvider>,
  )
}

/** Minimal FileList for tests (jsdom has no DataTransfer). */
function asFileList(files: File[]): FileList {
  const list = {
    length: files.length,
    item: (index: number) => files[index] ?? null,
  } as FileList
  for (let i = 0; i < files.length; i += 1) {
    Object.defineProperty(list, i, { value: files[i], enumerable: true })
  }
  return list
}

function radiatorFileInput(): HTMLInputElement {
  const heading = screen.getByRole('heading', { name: 'Radiators' })
  const slot = heading.closest('.photo-slot')
  const input = slot?.querySelector('input[type="file"]')
  if (!input) throw new Error('radiator file input missing')
  return input as HTMLInputElement
}

describe('CaptureScreen cover-up queue', () => {
  afterEach(() => {
    cleanup()
  })

  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('reads selected files before clearing the input value', async () => {
    renderCapture()
    const input = radiatorFileInput()
    const file = new File(['a'], 'snap.jpg', { type: 'image/jpeg' })
    fireEvent.change(input, { target: { files: asFileList([file]) } })
    await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument())
    expect(input.value).toBe('')
  })

  it('clears the file input after cancel so the same file reopens the dialog', async () => {
    const user = userEvent.setup()
    renderCapture()
    const input = radiatorFileInput()
    const file = new File(['a'], 'same.jpg', { type: 'image/jpeg' })

    await user.upload(input, file)
    await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(input.value).toBe('')

    await user.upload(input, file)
    await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument())
  })

  it('queues multiple radiator photos and skips one without dropping the rest', async () => {
    const user = userEvent.setup()
    renderCapture()
    const input = radiatorFileInput()
    const files = [
      new File(['1'], 'one.jpg', { type: 'image/jpeg' }),
      new File(['2'], 'two.jpg', { type: 'image/jpeg' }),
      new File(['3'], 'three.jpg', { type: 'image/jpeg' }),
    ]

    await user.upload(input, files)
    await waitFor(() => expect(screen.getByText('Photo 1 of 3')).toBeInTheDocument())

    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(screen.getByText('Photo 2 of 3')).toBeInTheDocument())

    await user.click(screen.getByRole('button', { name: 'Use photo' }))
    await waitFor(() => expect(screen.getByText('Photo 3 of 3')).toBeInTheDocument())

    await user.click(screen.getByRole('button', { name: 'Use photo' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('allows multi-select on the radiator file input', () => {
    renderCapture()
    expect(radiatorFileInput().hasAttribute('multiple')).toBe(true)
  })
})
