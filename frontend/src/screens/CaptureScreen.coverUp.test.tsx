import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
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
    onCancelAll,
    onConfirm,
  }: {
    progressLabel?: string
    onCancel: () => void
    onConfirm: (f: File) => void
    onCancelAll?: () => void
  }) => (
    <div role="dialog" aria-label="cover-up-mock">
      {progressLabel && <p>{progressLabel}</p>}
      <button type="button" onClick={onCancel}>Cancel</button>
      {onCancelAll && <button type="button" onClick={onCancelAll}>Cancel all</button>}
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

/** Presses "+ Add radiator" on the Radiators row and returns that radiator card's photo input. */
async function addRadiatorAndGetPhotoInput(user: ReturnType<typeof userEvent.setup>, number = 1) {
  const add = screen.getAllByRole('button', { name: /Add radiator/i })[0]
  await user.click(add)
  return screen.getByLabelText(`Add photos of Radiator ${number}`) as HTMLInputElement
}

async function useAllPhotos(user: ReturnType<typeof userEvent.setup>, total: number) {
  for (let i = 1; i <= total; i += 1) {
    if (total > 1) await waitFor(() => expect(screen.getByText(`Photo ${i} of ${total}`)).toBeInTheDocument())
    else await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: 'Use photo' }))
  }
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
}

describe('CaptureScreen cover-up queue', () => {
  afterEach(() => {
    cleanup()
  })

  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('reads selected files before clearing the input value', async () => {
    const user = userEvent.setup()
    renderCapture()
    const input = await addRadiatorAndGetPhotoInput(user)
    const file = new File(['a'], 'snap.jpg', { type: 'image/jpeg' })
    fireEvent.change(input, { target: { files: asFileList([file]) } })
    await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument())
    expect(input.value).toBe('')
  })

  it('clears the file input after cancel so the same file reopens the dialog', async () => {
    const user = userEvent.setup()
    renderCapture()
    const input = await addRadiatorAndGetPhotoInput(user)
    const file = new File(['a'], 'same.jpg', { type: 'image/jpeg' })

    await user.upload(input, file)
    await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(input.value).toBe('')

    await user.upload(input, file)
    await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument())
  })

  it('queues several photos of one radiator and skips one without dropping the rest', async () => {
    const user = userEvent.setup()
    renderCapture()
    const input = await addRadiatorAndGetPhotoInput(user)
    expect(input.hasAttribute('multiple')).toBe(true)
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
    expect(screen.getByText(/2 of 3 photos: all read together as this one radiator/)).toBeInTheDocument()
  })

  it('keeps two photos on one radiator card and supports retake and remove per photo', async () => {
    const user = userEvent.setup()
    renderCapture()
    const input = await addRadiatorAndGetPhotoInput(user)
    await user.upload(input, [
      new File(['1'], 'lounge-front.jpg', { type: 'image/jpeg' }),
      new File(['2'], 'lounge-end.jpg', { type: 'image/jpeg' }),
    ])
    await useAllPhotos(user, 2)

    const cards = within(screen.getByRole('list', { name: 'Your radiators' })).getAllByRole('listitem', {
      name: /^Radiator \d/,
    })
    expect(cards).toHaveLength(1)
    expect(screen.getByAltText('Radiator 1 photo 1 preview')).toBeInTheDocument()
    expect(screen.getByAltText('Radiator 1 photo 2 preview')).toBeInTheDocument()
    expect(screen.getByText('(lounge-front.jpg)')).toBeInTheDocument()

    await user.upload(
      screen.getByLabelText('Retake Radiator 1 photo 1'),
      new File(['1b'], 'lounge-retake.jpg', { type: 'image/jpeg' }),
    )
    await useAllPhotos(user, 1)
    expect(screen.getByText('(lounge-retake.jpg)')).toBeInTheDocument()
    expect(screen.queryByText('(lounge-front.jpg)')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Remove Radiator 1 photo 1' }))
    expect(screen.queryByText('(lounge-retake.jpg)')).not.toBeInTheDocument()
    expect(screen.getByText('(lounge-end.jpg)')).toBeInTheDocument()
    expect(screen.getByText(/1 of 3 photos/)).toBeInTheDocument()
  })

  it('caps one radiator at 3 photos and warns when more are selected', async () => {
    const user = userEvent.setup()
    renderCapture()
    const input = await addRadiatorAndGetPhotoInput(user)
    const files = Array.from({ length: 4 }, (_, i) =>
      new File([String(i)], `rad-${i + 1}.jpg`, { type: 'image/jpeg' }),
    )

    await user.upload(input, files)
    await waitFor(() => expect(screen.getByText('Photo 1 of 3')).toBeInTheDocument())
    expect(screen.getByRole('alert')).toHaveTextContent(/up to 3 per radiator/i)
  })

  it('clears the over-limit notice once the queue is done', async () => {
    const user = userEvent.setup()
    renderCapture()
    const input = await addRadiatorAndGetPhotoInput(user)
    const files = Array.from({ length: 4 }, (_, i) => new File([String(i)], `rad-${i}.jpg`, { type: 'image/jpeg' }))
    await user.upload(input, files)
    await waitFor(() => expect(screen.getByText('Photo 1 of 3')).toBeInTheDocument())
    expect(screen.getByText(/Only the first 3 photos queued/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Use photo' }))
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    await user.click(screen.getByRole('button', { name: 'Use photo' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(screen.queryByText(/Only the first 3 photos queued/)).not.toBeInTheDocument()
  })

  it('cancels the whole remaining batch in one go', async () => {
    const user = userEvent.setup()
    renderCapture()
    const input = await addRadiatorAndGetPhotoInput(user)
    await user.upload(input, [
      new File(['1'], 'one.jpg', { type: 'image/jpeg' }),
      new File(['2'], 'two.jpg', { type: 'image/jpeg' }),
      new File(['3'], 'three.jpg', { type: 'image/jpeg' }),
    ])
    await waitFor(() => expect(screen.getByText('Photo 1 of 3')).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: 'Cancel all' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(screen.queryByAltText('Radiator 1 photo 1 preview')).not.toBeInTheDocument()
  })

  it('offers Replace on a finished slot and shows its verdict once', async () => {
    const user = userEvent.setup()
    renderCapture()
    const toggle = screen
      .getAllByRole('button', { name: /Boiler data plate/i })
      .find((el) => el.classList.contains('capture-slot-disclosure'))!
    const slot = toggle.closest('.capture-slot-accordion') as HTMLElement
    const input = slot.querySelector('input[type="file"]') as HTMLInputElement
    await user.upload(input, new File(['b'], 'plate.jpg', { type: 'image/jpeg' }))
    await useAllPhotos(user, 1)
    await waitFor(() => expect(within(slot).getByText('Replace photo')).toBeInTheDocument())
    expect(within(slot).queryByText('Take photo or upload')).not.toBeInTheDocument()
    // The slot is open after the check: the verdict shows in the panel only, not twice.
    expect(within(slot).getByRole('button', { name: /Boiler data plate/i })).toHaveAttribute('aria-expanded', 'true')
    expect(slot.querySelectorAll('.capture-slot-verdict, .check-result')).toHaveLength(1)
    await user.click(toggle)
    expect(slot.querySelectorAll('.capture-slot-verdict, .check-result')).toHaveLength(1)
  })

  it('labels each radiator and stops adding at 8 radiators', async () => {
    const user = userEvent.setup()
    renderCapture()
    await addRadiatorAndGetPhotoInput(user, 1)
    await addRadiatorAndGetPhotoInput(user, 2)
    const second = screen.getByRole('listitem', { name: /^Radiator 2/ })
    await user.selectOptions(within(second).getByLabelText('Room'), 'Main bedroom')
    await user.type(within(second).getByLabelText('Note (optional)'), 'by the door')
    expect(within(second).getByRole('heading', { name: /Radiator 2 · Main bedroom – by the door/ })).toBeInTheDocument()

    for (let n = 3; n <= 8; n += 1) await addRadiatorAndGetPhotoInput(user, n)
    expect(screen.getByText(/most we check \(8 radiators\)/)).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: /Add radiator/i }).every((b) => (b as HTMLButtonElement).disabled)).toBe(true)
  })

  it('hides known details until expanded and checks entered ranges', async () => {
    const user = userEvent.setup()
    renderCapture()
    await addRadiatorAndGetPhotoInput(user)
    const card = screen.getByRole('listitem', { name: /^Radiator 1/ })
    const expander = within(card).getByText('Add details you know').closest('details')!
    expect(expander.open).toBe(false)

    await user.click(within(card).getByText('Add details you know'))
    expect(expander.open).toBe(true)
    await user.selectOptions(within(card).getByLabelText('Type'), 'K2')
    expect(within(card).getByText(/2 panels and 2 fin rows/)).toBeInTheDocument()
    await user.type(within(card).getByLabelText('Width'), '90')
    expect(within(card).getByText('Enter 300–3000 mm.')).toBeInTheDocument()
    await user.type(within(card).getByLabelText('Panels'), '1')
    expect(within(card).getByText('This type has 2 panels.')).toBeInTheDocument()
    await user.clear(within(card).getByLabelText('Width'))
    await user.type(within(card).getByLabelText('Width'), '1200')
    expect(within(card).queryByText('Enter 300–3000 mm.')).not.toBeInTheDocument()
    expect(within(card).getByText('2 added')).toBeInTheDocument()
  })
})
