import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, isMockMode } from '../api'
import { ImageCoverUp } from '../components/ImageCoverUp'
import { RadiatorVideoResults } from '../components/RadiatorVideoResults'
import { useSession } from '../context/SessionContext'
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
  const [pending, setPending] = useState<PendingCoverUp | null>(null)
  const [photoErrors, setPhotoErrors] = useState<Record<string, string>>({})
  const [prepareError, setPrepareError] = useState<string | null>(null)
  const [videoError, setVideoError] = useState<string | null>(null)
  const [examplesKind, setExamplesKind] = useState<PhotoKind | null>(null)
  const examplesTriggerRef = useRef<HTMLButtonElement | null>(null)
  const [whyNeedId, setWhyNeedId] = useState<WhyNeedId | null>(null)
  const whyNeedTriggerRef = useRef<HTMLButtonElement | null>(null)

  useEffect(() => {
    return () => {
      if (pending?.url) URL.revokeObjectURL(pending.url)
    }
  }, [pending])

  const onFile = async (kind: PhotoKind, file: File | null) => {
    if (!file) return
    setPrepareError(null)
    try {
      const prepared = await prepareImageFile(file)
      const url = URL.createObjectURL(prepared)
      setPending({ kind, url, fileName: file.name })
    } catch {
      setPrepareError('Could not prepare that image. Try another photo.')
    }
  }

  const closePending = () => {
    if (pending?.url) URL.revokeObjectURL(pending.url)
    setPending(null)
  }

  const onCoverUpConfirm = async (redacted: File) => {
    if (!pending) return
    const { kind } = pending
    closePending()
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
                type="file"
                accept="image/*"
                capture="environment"
                onChange={(e) => void onFile(slot.kind, e.target.files?.[0] ?? null)}
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

      {pending && (
        <ImageCoverUp
          imageUrl={pending.url}
          title={coverUpTitle(pending.kind)}
          guidance={coverUpGuidance(pending.kind)}
          fileName={pending.fileName}
          onConfirm={(f) => void onCoverUpConfirm(f)}
          onCancel={closePending}
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
