import { afterEach, expect, it, vi } from 'vitest'
import { searchEpcAddresses } from './client'
import { SAM_EPC_ADDRESSES } from './samMocks'

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
