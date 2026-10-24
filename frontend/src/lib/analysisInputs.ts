import type { PhotoKind, RadiatorUpload } from '../api'
import type { RadiatorCard } from '../context/SessionContext'
import type { DetailInputs } from '../lib/knownDetails'

function stableJson(value: unknown): string {
  return JSON.stringify(value)
}

const INPUT_KINDS: PhotoKind[] = [
  'boiler_plate',
  'radiators',
  'fuse_cutout',
  'outdoor_space',
  'loft',
  'gas_bill',
]

export type AnalysisInputsSnapshot = {
  certificateId: string | undefined
  files: Partial<Record<PhotoKind, File>>
  radiatorUploads: RadiatorUpload[]
  radiatorLabels: (string | null)[]
  radiators: RadiatorCard[]
  boilerDetails: DetailInputs
  fuseDetails: DetailInputs
  radiatorVideo: File | null
}

/** Stable fingerprint of capture inputs used for the last analysis run. */
export function analysisInputsFingerprint(snapshot: AnalysisInputsSnapshot): string {
  const {
    certificateId,
    files,
    radiatorUploads,
    radiatorLabels,
    radiators,
    boilerDetails,
    fuseDetails,
    radiatorVideo,
  } = snapshot
  const parts = [certificateId ?? '']
  for (const kind of INPUT_KINDS) {
    const file = files[kind]
    if (file) parts.push(`${kind}:${file.name}:${file.size}:${file.lastModified}`)
  }
  radiatorUploads.forEach((upload, index) => {
    parts.push(`rad-upload:${index}:${stableJson(upload.known)}`)
    upload.photos.forEach((file: File, photoIndex: number) => {
      parts.push(`rad-file:${index}:${photoIndex}:${file.name}:${file.size}:${file.lastModified}`)
    })
  })
  radiatorLabels.forEach((label, index) => {
    parts.push(`rad-label:${index}:${label ?? ''}`)
  })
  radiators.forEach((card) => {
    parts.push(
      `rad-card:${card.id}:${card.room}:${card.note}:${stableJson(card.details)}`,
    )
  })
  parts.push(`boiler:${stableJson(boilerDetails)}`)
  parts.push(`fuse:${stableJson(fuseDetails)}`)
  if (radiatorVideo) {
    parts.push(`radiator_video:${radiatorVideo.name}:${radiatorVideo.size}:${radiatorVideo.lastModified}`)
  }
  return parts.join('|')
}
