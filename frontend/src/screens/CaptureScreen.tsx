import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, isMockMode } from '../api'
import { ImageCoverUp } from '../components/ImageCoverUp'
import { RadiatorVideoResults } from '../components/RadiatorVideoResults'
import { useSession } from '../context/SessionContext'
import { resetFileInput } from '../lib/fileInputReset'
import { prepareImageFile } from '../lib/imagePrepare'
import { CaptureExamplesDialog } from '../components/CaptureExamplesDialog'
import { CaptureGuideSummary } from '../components/CaptureGuideSummary'
import { CaptureWhyNeedDialog } from '../components/CaptureWhyNeedDialog'
import { WhyNeedTrigger } from '../components/WhyNeedTrigger'
import type { WhyNeedId } from '../lib/captureWhyNeed'
import { CAPTURE_GUIDANCE } from '../lib/captureGuide'
import { coverUpGuidance, coverUpTitle } from '../lib/photoGuidance'
import type { PhotoKind } from '../api'

const VIDEO_MAX_BYTES = 100 * 1024 * 1024

type PendingCoverUp = {
  kind: PhotoKind
  url: string
  fileName: string
}

const MULTI_PHOTO_KINDS: PhotoKind[] = ['radiators']

export function CaptureScreen() {
  const {
    photos,
    setPhoto,
    radiatorVideo,
    radiatorVideoResult,
    setRadiatorVideo,
    placeLabel,
  } = useSession()
  const [busy, setBusy] = useState<Record<string, boolean>>({})
  const [coverCurrent, setCoverCurrent] = useState<PendingCoverUp | null>(null)
  const [coverStack, setCoverStack] = useState<PendingCoverUp[]>([])
  const [coverBatch, setCoverBatch] = useState<{ index: number; total: number } | null>(null)
  const fileInputsRef = useRef<Partial<Record<PhotoKind, HTMLInputElement>>>({})
  const coverQueueRef = useRef<PendingCoverUp[]>([])
  const [photoErrors, setPhotoErrors] = useState<Record<string, string>>({})
  const [prepareError, setPrepareError] = useState<string | null>(null)
  const [videoError, setVideoError] = useState<string | null>(null)
  const [examplesKind, setExamplesKind] = useState<PhotoKind | null>(null)
  const examplesTriggerRef = useRef<HTMLButtonElement | null>(null)
  const [whyNeedId, setWhyNeedId] = useState<WhyNeedId | null>(null)
  const whyNeedTriggerRef = useRef<HTMLButtonElement | null>(null)

  useEffect(() => {
    coverQueueRef.current = coverCurrent ? [coverCurrent, ...coverStack] : coverStack
  }, [coverCurrent, coverStack])

  useEffect(() => {
    return () => {
      for (const item of coverQueueRef.current) URL.revokeObjectURL(item.url)
    }
  }, [])

  const revokeCoverQueue = (current: PendingCoverUp | null, stack: PendingCoverUp[]) => {
    if (current?.url) URL.revokeObjectURL(current.url)
    for (const item of stack) URL.revokeObjectURL(item.url)
  }

  const advanceCoverQueue = () => {
    if (!coverCurrent) return
    URL.revokeObjectURL(coverCurrent.url)
    if (coverStack.length === 0) {
      setCoverCurrent(null)
      setCoverBatch(null)
      return
    }
    const [next, ...rest] = coverStack
    setCoverCurrent(next)
    setCoverStack(rest)
    setCoverBatch((b) => (b ? { ...b, index: b.index + 1 } : null))
  }

  const onFiles = async (kind: PhotoKind, list: FileList | null, input: HTMLInputElement) => {
    const allowMulti = MULTI_PHOTO_KINDS.includes(kind)
    const picked = list?.length
      ? allowMulti
        ? Array.from(list)
        : [list[0]]
      : []
    resetFileInput(input)
    if (picked.length === 0) return
    setPrepareError(null)
    revokeCoverQueue(coverCurrent, coverStack)
    setCoverCurrent(null)
    setCoverStack([])
    setCoverBatch(null)
    try {
      const queue: PendingCoverUp[] = []
      for (const file of picked) {
        const prepared = await prepareImageFile(file)
        queue.push({ kind, url: URL.createObjectURL(prepared), fileName: file.name })
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
    if (coverCurrent) resetFileInput(fileInputsRef.current[coverCurrent.kind])
  }

  const onCoverUpConfirm = async (redacted: File) => {
    if (!coverCurrent) return
    const { kind } = coverCurrent
    resetFileInput(fileInputsRef.current[kind])
    advanceCoverQueue()
    setPhotoErrors((errors) => ({ ...errors, [kind]: '' }))
    setBusy((b) => ({ ...b, [kind]: true }))
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
      setBusy((b) => ({ ...b, [kind]: false }))
    }
  }

  const onVideoFile = async (file: File | null) => {
    if (!file) return
    setVideoError(null)
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
      <h1>Capture</h1>
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

      <CaptureGuideSummary />

      {prepareError && <p className="warning">{prepareError}</p>}

      <div className="photo-grid">
        {photos.map((slot) => (
          <div key={slot.kind} className="photo-slot card">
            <div className="photo-slot-header">
              <h2>{slot.label}</h2>
              <div className="capture-slot-actions">
                <WhyNeedTrigger
                  onActivate={(el) => {
                    whyNeedTriggerRef.current = el
                    setWhyNeedId(slot.kind)
                  }}
                />
                <button
                  type="button"
                  className="btn capture-examples-trigger"
                  onClick={(e) => {
                    examplesTriggerRef.current = e.currentTarget
                    setExamplesKind(slot.kind)
                  }}
                >
                  See examples
                </button>
              </div>
            </div>
            <p className="capture-item-guidance">{CAPTURE_GUIDANCE[slot.kind].oneLine}</p>
            {CAPTURE_GUIDANCE[slot.kind].detail && (
              <p className="subtle capture-item-detail">{CAPTURE_GUIDANCE[slot.kind].detail}</p>
            )}
            <label className="upload-btn">
              <input
                ref={(el) => {
                  if (el) fileInputsRef.current[slot.kind] = el
                }}
                type="file"
                accept="image/*"
                capture="environment"
                multiple={MULTI_PHOTO_KINDS.includes(slot.kind)}
                onChange={(e) => void onFiles(slot.kind, e.target.files, e.currentTarget)}
              />
              {busy[slot.kind] ? 'Checking…' : 'Take photo or upload'}
            </label>
            {photoErrors[slot.kind] && <p className="error" role="alert">{photoErrors[slot.kind]}</p>}
            {slot.fileName && <p className="file-name">Redacted photo ready</p>}
            {slot.result && (
              <div className={`check-result ${slot.result.legible ? 'ok' : 'warn'}`}>
                <p>
                  {slot.result.summary}{' '}
                  <span className="subtle">
                    ({slot.result.model}, {(slot.result.elapsed_ms / 1000).toFixed(1)}s)
                  </span>
                </p>
                {!slot.result.matches_expected && (
                  <p className="retake">
                    {slot.result.kind === 'other'
                      ? `This doesn't look like a ${slot.label.replace(' (optional)', '').toLowerCase()}.`
                      : `This looks like a ${slot.result.kind.replaceAll('_', ' ')}.`}
                  </p>
                )}
                {slot.result.retake_hint && <p className="retake">{slot.result.retake_hint}</p>}
                {slot.result.privacy_warning && (
                  <p className="privacy-warn">{slot.result.privacy_warning}</p>
                )}
                {!slot.result.privacy_warning && slot.result.legible && (
                  <p className="privacy-ok">Redacted image only — no metadata stored.</p>
                )}
              </div>
            )}

            {slot.kind === 'radiators' && (
              <div className="video-capture-option">
                <div className="video-capture-header">
                  <h3>Or film your radiators</h3>
                  <WhyNeedTrigger
                    onActivate={(el) => {
                      whyNeedTriggerRef.current = el
                      setWhyNeedId('radiator_video')
                    }}
                  />
                </div>
                <p className="privacy-warn">
                  Video is not covered up like photos: film radiators only, close, with no windows,
                  people or house numbers.
                </p>
                <p className="subtle">
                  GPS, device and timestamp metadata are stripped server-side before Gemini sees the
                  video (max 90 s, 100 MB). Uncertain radiators become photo requests, never guesses.
                </p>
                <label className="upload-btn">
                  <input
                    type="file"
                    accept="video/mp4,video/quicktime,video/webm,video/*"
                    capture="environment"
                    onChange={(e) => void onVideoFile(e.target.files?.[0] ?? null)}
                  />
                  {busy.radiator_video ? 'Watching video…' : 'Film radiators or upload video'}
                </label>
                {radiatorVideo && !busy.radiator_video && (
                  <p className="file-name">Radiator walkthrough video ready</p>
                )}
                {videoError && <p className="error">{videoError}</p>}
                {radiatorVideoResult && <RadiatorVideoResults result={radiatorVideoResult} />}
              </div>
            )}
          </div>
        ))}
      </div>

      {examplesKind && (
        <CaptureExamplesDialog
          kind={examplesKind}
          title={photos.find((p) => p.kind === examplesKind)?.label ?? examplesKind}
          returnFocusTo={examplesTriggerRef.current}
          onClose={() => setExamplesKind(null)}
        />
      )}

      {whyNeedId && (
        <CaptureWhyNeedDialog
          id={whyNeedId}
          returnFocusTo={whyNeedTriggerRef.current}
          onClose={() => setWhyNeedId(null)}
        />
      )}

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
