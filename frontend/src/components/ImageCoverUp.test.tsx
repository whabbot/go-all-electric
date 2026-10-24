import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { ImageCoverUp } from './ImageCoverUp'

afterEach(() => cleanup())

function renderDialog(extra: { onCancelAll?: () => void } = {}) {
  const onCancel = vi.fn()
  render(
    <ImageCoverUp imageUrl="blob:synthetic" title="Redact" fileName="rad.jpg" onConfirm={vi.fn()} onCancel={onCancel} {...extra} />,
  )
  return onCancel
}

it('Escape behaves like Cancel', async () => {
  const onCancel = renderDialog()
  await userEvent.keyboard('{Escape}')
  expect(onCancel).toHaveBeenCalledOnce()
  expect(screen.getByRole('button', { name: 'Cancel' })).toBeInTheDocument()
})

it('offers Cancel all next to Skip this photo when more photos are queued', async () => {
  const onCancelAll = vi.fn()
  const onCancel = renderDialog({ onCancelAll })
  await userEvent.click(screen.getByRole('button', { name: 'Cancel all' }))
  expect(onCancelAll).toHaveBeenCalledOnce()
  await userEvent.click(screen.getByRole('button', { name: 'Skip this photo' }))
  expect(onCancel).toHaveBeenCalledOnce()
})
