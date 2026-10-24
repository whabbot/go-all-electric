import { afterEach, expect, it, vi } from 'vitest'
import { runAnalysis, searchEpcAddresses } from './client'
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

it('appends multiple radiator files to the analysis FormData and returns multiple Sam radiator readings in mock mode', async () => {
  const samResult = mockAnalysisResult(['boiler_plate', 'radiators', 'fuse_cutout', 'gas_bill'])
  const radReadings = samResult.readings.filter((r) => r.kind === 'radiators')
  expect(radReadings).toHaveLength(2)
  expect(samResult.bundle.target_spec.radiators.length).toBeGreaterThanOrEqual(2)

  vi.stubEnv('VITE_USE_MOCKS', 'false')
  let capturedBody: FormData | null = null
  const fetchMock = vi.fn().mockImplementation(async (_url: string, init?: RequestInit) => {
    capturedBody = init?.body as FormData
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(
          new TextEncoder().encode(`${JSON.stringify({ type: 'result', result: samResult })}\n`),
        )
        controller.close()
      },
    })
    return {
      ok: true,
      status: 200,
      body: stream,
    }
  })
  vi.stubGlobal('fetch', fetchMock)

  const rad1 = new File(['r1'], 'rad1.jpg', { type: 'image/jpeg' })
  const rad2 = new File(['r2'], 'rad2.jpg', { type: 'image/jpeg' })
  await runAnalysis('cert-1', {}, () => {}, null, [rad1, rad2])

  expect(capturedBody).not.toBeNull()
  expect(capturedBody!.getAll('radiators')).toHaveLength(2)
})
