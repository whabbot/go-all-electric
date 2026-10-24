import { afterEach, expect, it, vi } from 'vitest'
import { reviewAnalysis, runAnalysis, searchEpcAddresses } from './client'
import { mockAnalysisResult, SAM_EPC_ADDRESSES } from './samMocks'

afterEach(() => {
  vi.unstubAllGlobals()
  vi.unstubAllEnvs()
})

it('sends the postcode in a JSON body and preserves the search response', async () => {
  vi.stubEnv('VITE_USE_MOCKS', 'false')
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => ({ addresses: SAM_EPC_ADDRESSES }),
  })
  vi.stubGlobal('fetch', fetchMock)
  const postcode = 'ZZ1 1ZZ'

  expect(await searchEpcAddresses(postcode)).toEqual(SAM_EPC_ADDRESSES)
  expect(fetchMock).toHaveBeenCalledExactlyOnceWith('/api/epc/search', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ postcode }),
    credentials: 'same-origin',
  })
})

function streamOf(result: unknown) {
  return new ReadableStream({
    start(controller) {
      controller.enqueue(new TextEncoder().encode(`${JSON.stringify({ type: 'result', result })}\n`))
      controller.close()
    },
  })
}

/** Everything a request carries, as text: form field names, values and file names. */
function formText(form: FormData): string {
  const parts: string[] = []
  for (const [key, value] of form.entries()) {
    parts.push(key, typeof value === 'string' ? value : value.name)
  }
  return parts.join('\n')
}

const LABEL = "Jamie's room"

it('sends two photos of one radiator as one radiator, with entered details and no labels', async () => {
  vi.stubEnv('VITE_USE_MOCKS', 'false')
  let captured: FormData | null = null
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation(async (_url: string, init?: RequestInit) => {
      captured = init?.body as FormData
      return { ok: true, status: 200, body: streamOf(mockAnalysisResult(['gas_bill'])) }
    }),
  )
  const front = new File(['f'], 'rad1-front.jpg', { type: 'image/jpeg' })
  const end = new File(['e'], 'rad1-end.jpg', { type: 'image/jpeg' })
  const other = new File(['o'], 'rad2.jpg', { type: 'image/jpeg' })
  // The card's label (room + note) is not part of RadiatorUpload: there is nothing to leak.
  await runAnalysis(
    'cert-1',
    {},
    () => {},
    null,
    [
      { photos: [front, end], known: { width_mm: 1200 } },
      { photos: [], known: { radiator_type: 'K2', width_mm: 1000, height_mm: 600 } },
      { photos: [other], known: {} },
    ],
    { boiler: { make: 'Worcester Bosch' }, fuse_cutout: { rating_a: 100 } },
  )

  const form = captured! as FormData
  expect(form.getAll('radiators')).toHaveLength(3)
  expect(form.getAll('radiator_index')).toEqual(['0', '0', '2'])
  expect(JSON.parse(form.get('known') as string)).toEqual({
    radiators: [{ width_mm: 1200 }, { radiator_type: 'K2', width_mm: 1000, height_mm: 600 }, {}],
    boiler: { make: 'Worcester Bosch' },
    fuse_cutout: { rating_a: 100 },
  })
  const text = formText(form)
  expect(text).not.toContain(LABEL)
  expect(text).not.toMatch(/label|room/i)
})

it('reviews radiators by number with entered values and photo disagreements, never labels', async () => {
  vi.stubEnv('VITE_USE_MOCKS', 'false')
  const analysis = mockAnalysisResult(['gas_bill', 'boiler_plate'], false, [
    { photos: [new File(['f'], 'f.jpg')], known: { width_mm: 1500 } },
    { photos: [], known: { radiator_type: 'K1', width_mm: 800, height_mm: 600 } },
  ], { radiators: [], boiler: { heating_output_kw: 30 }, fuse_cutout: null })
  let captured: FormData | null = null
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation(async (_url: string, init?: RequestInit) => {
      captured = init?.body as FormData
      return { ok: true, status: 200, json: async () => ({}) }
    }),
  )
  const photos = [new File(['f'], 'rad1-front.jpg'), new File(['e'], 'rad1-end.jpg')]
  await reviewAnalysis(analysis, {}, [], [{ photos, known: {} }])

  const form = captured! as FormData
  expect(form.getAll('radiator_index')).toEqual(['0', '0'])
  const context = JSON.parse(form.get('context') as string)
  // Positional: radiator 1 read from its photo; radiator 2 entered only, so no reading.
  expect(context.radiators).toHaveLength(2)
  expect(context.radiators[0].width_mm).toBe(1500)
  expect(context.radiators[1]).toBeNull()
  expect(context.entered).toEqual(
    expect.arrayContaining([
      { input: 'radiators', radiator: 1, field: 'width_mm', entered: 1500, photo_read: 1200 },
      { input: 'radiators', radiator: 2, field: 'width_mm', entered: 800 },
      { input: 'boiler_plate', field: 'heating_output_kw', entered: 30, photo_read: 24 },
    ]),
  )
  expect(formText(form)).not.toContain(LABEL)
})

it('mock analysis reads two photos of one radiator as one and counts details-only radiators', () => {
  const result = mockAnalysisResult(['gas_bill'], false, [
    { photos: [new File(['a'], 'a.jpg'), new File(['b'], 'b.jpg')], known: {} },
    { photos: [], known: { radiator_type: 'K2', width_mm: 1000, height_mm: 600 } },
  ])
  const radiators = result.readings.filter((r) => r.kind === 'radiators')
  expect(radiators.map((r) => [r.index, r.status])).toEqual([
    [0, 'verified'],
    [1, 'entered'],
  ])
  expect(result.bundle.target_spec.radiators.map((r) => r.room)).toEqual(['Radiator 1', 'Radiator 2'])
})

it('the Sam sample still has two photographed radiators', () => {
  const sam = mockAnalysisResult(['boiler_plate', 'radiators', 'fuse_cutout', 'gas_bill'])
  expect(sam.readings.filter((r) => r.kind === 'radiators' && r.status === 'verified')).toHaveLength(2)
})
