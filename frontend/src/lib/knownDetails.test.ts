import { expect, it } from 'vitest'
import {
  applyEntered,
  parseKnownBoiler,
  parseKnownFuse,
  parseKnownRadiator,
  radiatorLabel,
  radiatorName,
  specRoomName,
} from './knownDetails'

it('an entered value wins and a disagreeing photo reading is kept, not dropped', () => {
  const { reading, disagreements } = applyEntered(
    { width_mm: 1400, height_mm: 600, radiator_type: 'K2', make: 'Worcester' },
    { width_mm: 1200, height_mm: 590, make: 'Worcester Bosch' },
  )
  expect(reading).toMatchObject({ width_mm: 1200, height_mm: 590, make: 'Worcester Bosch' })
  // 600 vs 590 mm is within the photo's tolerance; "Worcester" is part of "Worcester Bosch".
  expect(disagreements).toEqual([{ field: 'width_mm', entered: 1200, read: 1400 }])
})

it('checks entered ranges and that panels match the type', () => {
  expect(parseKnownRadiator({ width_mm: '90', fin_rows: '2.5' }).errors).toEqual({
    width_mm: 'Enter 300–3000 mm.',
    fin_rows: 'Enter a whole number.',
  })
  const k2 = parseKnownRadiator({ radiator_type: 'K2', panels: '1', fin_rows: '2', height_mm: ' 600 ' })
  expect(k2.known).toEqual({ radiator_type: 'K2', fin_rows: 2, height_mm: 600 })
  expect(k2.errors.panels).toBe('This type has 2 panels.')
  expect(parseKnownBoiler({ make: '  Ideal  Logic ', heating_output_kw: '200' })).toEqual({
    known: { make: 'Ideal Logic' },
    errors: { heating_output_kw: 'Enter 3–70 kW.' },
  })
  expect(parseKnownBoiler({ model: 'ZZ1 1ZZ' }).errors.model).toBe('Enter the make or model only.')
  expect(parseKnownFuse({ rating_a: '100' }).known).toEqual({ rating_a: 100 })
  expect(parseKnownFuse({ rating_a: '70' }).known).toEqual({})
})

it('shows radiators by number with the homeowner label, else the room Gemini saw', () => {
  const labels = [radiatorLabel('Main bedroom', ' by the door '), radiatorLabel('', '')]
  const readings = [
    { kind: 'radiators' as const, index: 1, status: 'verified' as const, attempts: 1, reading: { room: 'Hall' }, warnings: [], photograph_instead: null, used_for: '' },
  ]
  expect(radiatorName(0, labels, readings)).toBe('Radiator 1 · Main bedroom – by the door')
  expect(radiatorName(1, labels, readings)).toBe('Radiator 2 · Hall')
  expect(radiatorName(2, labels, readings)).toBe('Radiator 3')
  expect(specRoomName('Radiator 1', labels, readings)).toBe('Radiator 1 · Main bedroom – by the door')
  expect(specRoomName('Dining room', labels, readings)).toBe('Dining room')
})
