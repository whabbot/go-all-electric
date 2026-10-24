import { describe, expect, it } from 'vitest'
import { resetFileInput } from './fileInputReset'

describe('resetFileInput', () => {
  it('clears the input value so the same file can be chosen again', () => {
    const input = document.createElement('input')
    input.type = 'file'
    Object.defineProperty(input, 'value', {
      writable: true,
      value: 'C:\\fakepath\\photo.jpg',
    })
    resetFileInput(input)
    expect(input.value).toBe('')
  })
})
