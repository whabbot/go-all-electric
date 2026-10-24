import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, isMockMode } from '../api'
import { ImageCoverUp } from '../components/ImageCoverUp'
import { CapturePhotoSlotList } from '../components/CapturePhotoSlotList'
import { MAX_PHOTOS_PER_RADIATOR, useSession } from '../context/SessionContext'
import { resetFileInput } from '../lib/fileInputReset'
import { prepareImageFile } from '../lib/imagePrepare'
import type { WhyNeedId } from '../lib/captureWhyNeed'
import type { PhotoKind } from '../api'
import { firstCaptureSlotNeedingAttention } from '../lib/captureGuide'
import { coverUpGuidance, coverUpTitle } from '../lib/photoGuidance'

const VIDEO_MAX_BYTES = 100 * 1024 * 1024

/** Radiator photos belong to one radiator card; a retake replaces one of its photos. */
type RadiatorTarget = { radiatorId: string; photoId?: string }

type PendingCoverUp = {
  kind: PhotoKind
  url: string
  fileName: string
  radiator?: RadiatorTarget
}

export function CaptureScreen() {
  const {
    photos,
    setPhoto,
    radiators,
    addRadiator,
    updateRadiator,
    removeRadiator,
    addRadiatorPhoto,
    updateRadiatorPhoto,
    removeRadiatorPhoto,
    boilerDetails,
    setBoilerDetails,
    fuseDetails,
    setFuseDetails,
    radiatorVideo,
    radiatorVideoResult,
    setRadiatorVideo,
    placeLabel,
  } = useSession()
  const [busy, setBusy] = useState<Record<string, boolean>>({})
  const activeChecksRef = useRef<Record<string, number>>({})
  const [coverCurrent, setCoverCurrent] = useState<PendingCoverUp | null>(null)
  const [coverStack, setCoverStack] = useState<PendingCoverUp[]>([])
  const [coverBatch, setCoverBatch] = useState<{ index: number; total: number } | null>(null)
  const fileInputsRef = useRef<Partial<Record<PhotoKind, HTMLInputElement>>>({})
  const coverQueueRef = useRef<PendingCoverUp[]>([])
  const [photoErrors, setPhotoErrors] = useState<Record<string, string>>({})
  const queueNoticeKeysRef = useRef<string[]>([])
  const [focusRadiatorId, setFocusRadiatorId] = useState<string | null>(null)
  const [prepareError, setPrepareError] = useState<string | null>(null)
  const [videoError, setVideoError] = useState<string | null>(null)
  const [examplesKind, setExamplesKind] = useState<PhotoKind | null>(null)
  const examplesTriggerRef = useRef<HTMLButtonElement | null>(null)
  const [whyNeedId, setWhyNeedId] = useState<WhyNeedId | null>(null)
  const whyNeedTriggerRef = useRef<HTMLButtonElement | null>(null)
  const [expandedKind, setExpandedKind] = useState<PhotoKind | null>(() =>
    firstCaptureSlotNeedingAttention(photos, radiatorVideo),
  )
  const prevBusyRef = useRef(busy)

  useEffect(() => {
    coverQueueRef.current = coverCurrent ? [coverCurrent, ...coverStack] : coverStack
  }, [coverCurrent, coverStack])

  useEffect(() => {
    return () => {
      for (const item of coverQueueRef.current) URL.revokeObjectURL(item.url)
    }
  }, [])

  useEffect(() => {
    for (const kind of Object.keys(busy)) {
      if (prevBusyRef.current[kind] && !busy[kind]) {
        setExpandedKind(kind as PhotoKind)
      }
    }
    prevBusyRef.current = busy
  }, [busy])

  const revokeCoverQueue = (current: PendingCoverUp | null, stack: PendingCoverUp[]) => {
    if (current?.url) URL.revokeObjectURL(current.url)
    for (const item of stack) URL.revokeObjectURL(item.url)
  }

  /** "Only the first N photos queued" is about this queue: it goes once the queue is done. */
  const clearQueueNotices = () => {
    const keys = queueNoticeKeysRef.current
    queueNoticeKeysRef.current = []
    if (keys.length > 0) {
      setPhotoErrors((errors) => {
        const next = { ...errors }
        for (const key of keys) delete next[key]
        return next
      })
    }
  }

  const advanceCoverQueue = () => {
    if (!coverCurrent) return
    URL.revokeObjectURL(coverCurrent.url)
    if (coverStack.length === 0) {
      setCoverCurrent(null)
      setCoverBatch(null)
      clearQueueNotices()
      return
    }
    const [next, ...rest] = coverStack
    setCoverCurrent(next)
    setCoverStack(rest)
    setCoverBatch((b) => (b ? { ...b, index: b.index + 1 } : null))
  }

  const onFiles = async (
    kind: PhotoKind,
    list: FileList | null,
    input: HTMLInputElement,
    radiator?: RadiatorTarget,
  ) => {
    const allowMulti = kind === 'radiators' && !radiator?.photoId
    let picked = list?.length
      ? allowMulti
        ? Array.from(list)
        : [list[0]]
      : []
    resetFileInput(input)
    if (picked.length === 0) return
    setPrepareError(null)
    setExpandedKind(kind)
    if (radiator && !radiator.photoId) {
      const errorKey = `radiators:${radiator.radiatorId}`
      const card = radiators.find((r) => r.id === radiator.radiatorId)
      const remaining = MAX_PHOTOS_PER_RADIATOR - (card?.photos.length ?? 0)
      if (remaining <= 0) {
        setPhotoErrors((errors) => ({
          ...errors,
          [errorKey]: `Up to ${MAX_PHOTOS_PER_RADIATOR} photos per radiator. Remove or retake one instead.`,
        }))
        return
      }
      if (picked.length > remaining) {
        picked = picked.slice(0, remaining)
        queueNoticeKeysRef.current = [errorKey]
        setPhotoErrors((errors) => ({
          ...errors,
          [errorKey]: `Only the first ${remaining} photo${remaining === 1 ? '' : 's'} queued (up to ${MAX_PHOTOS_PER_RADIATOR} per radiator).`,
        }))
      } else {
        setPhotoErrors((errors) => ({ ...errors, [errorKey]: '' }))
      }
    }
    revokeCoverQueue(coverCurrent, coverStack)
    setCoverCurrent(null)
    setCoverStack([])
    setCoverBatch(null)
    try {
      const queue: PendingCoverUp[] = []
      for (const file of picked) {
        const prepared = await prepareImageFile(file)
        queue.push({
          kind,
          url: URL.createObjectURL(prepared),
          fileName: file.name,
          radiator,
        })
      }
      if (queue.length === 0) return
      const [first, ...rest] = queue
      setCoverCurrent(first)
      setCoverStack(rest)
      setCoverBatch({ index: 1, total: queue.length })
    } catch {
      setPrepareError('Could not prepare that image. Try another photo.')
    }
  }

  const skipCoverCurrent = () => {
    if (coverCurrent) resetFileInput(fileInputsRef.current[coverCurrent.kind])
    advanceCoverQueue()
  }

  const cancelCoverFlow = () => {
    revokeCoverQueue(coverCurrent, coverStack)
    setCoverCurrent(null)
    setCoverStack([])
    setCoverBatch(null)
    clearQueueNotices()
    if (coverCurrent) resetFileInput(fileInputsRef.current[coverCurrent.kind])
  }

  const onCoverUpConfirm = async (redacted: File) => {
    if (!coverCurrent) return
    const { kind, fileName, radiator } = coverCurrent
    resetFileInput(fileInputsRef.current[kind])
    advanceCoverQueue()
    setPhotoErrors((errors) => ({ ...errors, [kind]: '' }))
    activeChecksRef.current[kind] = (activeChecksRef.current[kind] ?? 0) + 1
    setBusy((b) => ({ ...b, [kind]: true }))
    setExpandedKind(kind)
    if (radiator) {
      const { radiatorId } = radiator
      let photoId: string
      if (radiator.photoId) {
        photoId = radiator.photoId
        updateRadiatorPhoto(radiatorId, photoId, {
          file: redacted,
          fileName: fileName || redacted.name,
          previewUrl: URL.createObjectURL(redacted),
          result: null,
          checking: true,
          error: null,
        })
      } else {
        photoId = addRadiatorPhoto(radiatorId, redacted)
        if (fileName) {
          updateRadiatorPhoto(radiatorId, photoId, { fileName })
        }
      }
      try {
        const result = await api.checkPhoto('radiators', redacted)
        updateRadiatorPhoto(radiatorId, photoId, { result, checking: false, error: null })
      } catch (error: unknown) {
        const msg = error instanceof Error ? error.message : 'Could not check that photo.'
        updateRadiatorPhoto(radiatorId, photoId, { result: null, checking: false, error: msg })
      } finally {
        const left = Math.max(0, (activeChecksRef.current.radiators ?? 1) - 1)
        activeChecksRef.current.radiators = left
        if (left === 0) {
          setBusy((b) => ({ ...b, radiators: false }))
        }
      }
      return
    }
    // Only the redacted, re-encoded file is kept (in memory) and later sent for analysis.
    setPhoto(kind, redacted, null)
    try {
      const result = await api.checkPhoto(kind, redacted)
      setPhoto(kind, redacted, result)
    } catch (error: unknown) {
      setPhotoErrors((errors) => ({
        ...errors,
        [kind]: error instanceof Error ? error.message : 'Could not check that photo.',
      }))
      setPhoto(kind, redacted, null)
    } finally {
      const left = Math.max(0, (activeChecksRef.current[kind] ?? 1) - 1)
      activeChecksRef.current[kind] = left
      if (left === 0) {
        setBusy((b) => ({ ...b, [kind]: false }))
      }
    }
  }

  const onVideoFile = async (file: File | null) => {
    if (!file) return
    setVideoError(null)
    setExpandedKind('radiators')
    if (file.size === 0) {
      setVideoError('Empty video file.')
      return
    }
    if (file.size > VIDEO_MAX_BYTES) {
      setVideoError('Video is over 100 MB; film a shorter walkthrough (up to 90 seconds).')
      return
    }
    setBusy((b) => ({ ...b, radiator_video: true }))
    setRadiatorVideo(file, null)
    try {
      const result = await api.checkRadiatorVideo(file)
      setRadiatorVideo(file, result)
    } catch (e: unknown) {
      setRadiatorVideo(null, null)
      setVideoError(e instanceof Error ? e.message : 'Could not check that radiator video.')
    } finally {
      setBusy((b) => ({ ...b, radiator_video: false }))
    }
  }

  const anyBusy = Object.values(busy).some(Boolean)
  const noBill = !photos.find((p) => p.kind === 'gas_bill')?.fileName

  return (
    <section className="screen capture-screen">
      <h1>Photos</h1>
      {placeLabel ? (
        <p className="place-label">{placeLabel}</p>
      ) : (
        <p className="warning">
          Pick a house on <Link to="/">Start</Link>
          {isMockMode() ? ' — using the demo home for now.' : ' first.'}
        </p>
      )}

      <p className="lede">
        Use your camera or upload. Each photo is stripped of hidden metadata, you redact anything
        identifying, then we check it.
      </p>

      {prepareError && <p className="warning">{prepareError}</p>}

      <CapturePhotoSlotList
        photos={photos}
        expandedKind={expandedKind}
        onExpandedKindChange={setExpandedKind}
        busy={busy}
        photoErrors={photoErrors}
        onFiles={onFiles}
        fileInputsRef={fileInputsRef}
        radiators={radiators}
        focusRadiatorId={focusRadiatorId}
        onAddRadiator={() => setFocusRadiatorId(addRadiator())}
        onRemoveRadiator={removeRadiator}
        onRadiatorLabelChange={(id, patch) => updateRadiator(id, patch)}
        onRadiatorDetailsChange={(id, details) => updateRadiator(id, { details })}
        onAddRadiatorPhotos={(id, list, input) => void onFiles('radiators', list, input, { radiatorId: id })}
        onRetakeRadiatorPhoto={(id, photoId, list, input) =>
          void onFiles('radiators', list, input, { radiatorId: id, photoId })
        }
        onRemoveRadiatorPhoto={removeRadiatorPhoto}
        boilerDetails={boilerDetails}
        onBoilerDetailsChange={setBoilerDetails}
        fuseDetails={fuseDetails}
        onFuseDetailsChange={setFuseDetails}
        radiatorVideo={radiatorVideo}
        radiatorVideoResult={radiatorVideoResult}
        videoError={videoError}
        onVideoFile={onVideoFile}
        examplesKind={examplesKind}
        setExamplesKind={setExamplesKind}
        examplesTriggerRef={examplesTriggerRef}
        whyNeedId={whyNeedId}
        setWhyNeedId={setWhyNeedId}
        whyNeedTriggerRef={whyNeedTriggerRef}
      />

      {coverCurrent && (
        <ImageCoverUp
          key={coverCurrent.url}
          imageUrl={coverCurrent.url}
          title={coverUpTitle(coverCurrent.kind)}
          guidance={coverUpGuidance(coverCurrent.kind)}
          fileName={coverCurrent.fileName}
          progressLabel={
            coverBatch && coverBatch.total > 1
              ? `Photo ${coverBatch.index} of ${coverBatch.total}`
              : undefined
          }
          onConfirm={(f) => void onCoverUpConfirm(f)}
          onCancel={
            coverBatch && coverBatch.total > 1 ? skipCoverCurrent : cancelCoverFlow
          }
          onCancelAll={coverStack.length > 0 ? cancelCoverFlow : undefined}
        />
      )}

      {noBill && (
        <p className="subtle">
          No gas bill yet: you&apos;ll get the fabric estimate only, and we&apos;ll say what we can&apos;t compare.
        </p>
      )}

      {anyBusy && <p className="subtle">Wait for photo checks to finish before continuing.</p>}
    </section>
  )
}
