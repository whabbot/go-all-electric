import type { PhotoKind } from '../api'

const BILL_GUIDANCE =
  'Gemini only needs the kWh used and the dates. Cover your name, address, account and meter numbers. ' +
  'Crop to the usage panel if you can.'

export function coverUpTitle(kind: PhotoKind): string {
  if (kind === 'gas_bill') return 'Redact your gas bill'
  return 'Redact before upload'
}

export function coverUpGuidance(kind: PhotoKind): string | undefined {
  if (kind === 'gas_bill') return BILL_GUIDANCE
  return 'Cover house numbers, street signs, faces, cars, names, post and meter numbers.'
}

export const QUOTE_PAGE_GUIDANCE =
  'Cover installer letterheads, your address and any account numbers. Keep heat pump size, flow temperature and prices visible.'
