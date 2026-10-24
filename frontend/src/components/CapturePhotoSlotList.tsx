import { useId, type MutableRefObject } from 'react'
import type { PhotoCheckResult, PhotoKind, RadiatorVideoResult } from '../api'
import { CaptureExamplesDialog } from './CaptureExamplesDialog'
import { CaptureWhyNeedDialog } from './CaptureWhyNeedDialog'
import { RadiatorVideoResults } from './RadiatorVideoResults'
import { WhyNeedTrigger } from './WhyNeedTrigger'
import type { WhyNeedId } from '../lib/captureWhyNeed'
import {
  CAPTURE_CHECKLIST_HEADING,
  CAPTURE_CHECKLIST_INTRO,
  CAPTURE_CHECKLIST_TOTAL,
  CAPTURE_GUIDANCE,
  CAPTURE_STATUS_LABEL,
  CAPTURE_SUMMARY_ITEMS,
  captureSummaryForKind,
} from '../lib/captureGuide'

type PhotoSlot = {
  kind: PhotoKind
  label: string
  result: PhotoCheckResult | null
  fileName: string | null
}

type Props = {
  photos: PhotoSlot[]
  expandedKind: PhotoKind | null
  onExpandedKindChange: (kind: PhotoKind | null) => void
  busy: Record<string, boolean>
  photoErrors: Record<string, string>
  onFiles: (kind: PhotoKind, list: FileList | null, input: HTMLInputElement) => void
  fileInputsRef: MutableRefObject<Partial<Record<PhotoKind, HTMLInputElement>>>
  multiPhotoKinds: PhotoKind[]
  radiatorVideo: File | null
  radiatorVideoResult: RadiatorVideoResult | null
  videoError: string | null
  onVideoFile: (file: File | null) => void
  examplesKind: PhotoKind | null
  setExamplesKind: (kind: PhotoKind | null) => void
  examplesTriggerRef: MutableRefObject<HTMLButtonElement | null>
  whyNeedId: WhyNeedId | null
  setWhyNeedId: (id: WhyNeedId | null) => void
  whyNeedTriggerRef: MutableRefObject<HTMLButtonElement | null>
}

function slotDoneState(slot: PhotoSlot, radiatorVideo: File | null): 'empty' | 'checking' | 'ok' | 'warn' {
  if (slot.kind === 'radiators' && !slot.fileName && radiatorVideo) return 'ok'
  if (!slot.fileName) return 'empty'
  if (slot.result?.legible) return 'ok'
  if (slot.result) return 'warn'
  return 'checking'
}

export function CapturePhotoSlotList({
  photos,
  expandedKind,
  onExpandedKindChange,
  busy,
  photoErrors,
  onFiles,
  fileInputsRef,
  multiPhotoKinds,
  radiatorVideo,
  radiatorVideoResult,
  videoError,
  onVideoFile,
  examplesKind,
  setExamplesKind,
  examplesTriggerRef,
  whyNeedId,
  setWhyNeedId,
  whyNeedTriggerRef,
}: Props) {
  const listId = useId()

  const slotByKind = (kind: PhotoKind) => {
    const slot = photos.find((p) => p.kind === kind)
    if (!slot) throw new Error(`Missing photo slot ${kind}`)
    return slot
  }

  const toggleExpanded = (kind: PhotoKind) => {
    onExpandedKindChange(expandedKind === kind ? null : kind)
  }

  return (
    <section className="capture-checklist" aria-labelledby={`${listId}-heading`}>
      <h2 id={`${listId}-heading`}>{CAPTURE_CHECKLIST_HEADING}</h2>
      <p className="subtle capture-checklist-intro">{CAPTURE_CHECKLIST_INTRO}</p>
      <p className="subtle capture-checklist-total">{CAPTURE_CHECKLIST_TOTAL}</p>

      <ul className="capture-slot-list">
        {CAPTURE_SUMMARY_ITEMS.map((item) => {
          const kind = item.id as PhotoKind
          const slot = slotByKind(kind)
          const summary = captureSummaryForKind(kind)
          const panelId = `${listId}-panel-${kind}`
          const isExpanded = expandedKind === kind
          const done = slotDoneState(slot, radiatorVideo)
          const isChecking = Boolean(busy[kind])

          return (
            <li key={kind} className="capture-slot-accordion card">
              <div className="capture-slot-collapsed">
                <button
                  type="button"
                  className="capture-slot-disclosure"
                  aria-expanded={isExpanded}
                  aria-controls={panelId}
                  onClick={() => toggleExpanded(kind)}
                >
                  <span className="capture-guide-label">{summary.label}</span>
                  <span className={`capture-guide-status capture-guide-status--${summary.status}`}>
                    {CAPTURE_STATUS_LABEL[summary.status]}
                  </span>
                  {summary.reason ? (
                    <span className="capture-guide-reason subtle">{summary.reason}</span>
                  ) : null}
                  <span className="capture-guide-meta">
                    {summary.photoCount} · {summary.timeHint}
                    {done === 'ok' ? ' · Ready' : done === 'warn' ? ' · Needs attention' : ''}
                  </span>
                  {slot.result && done !== 'empty' && (
                    <span className="capture-slot-verdict subtle">{slot.result.summary}</span>
                  )}
                </button>
                <label className="upload-btn capture-slot-upload">
                  <input
                    ref={(el) => {
                      if (el) fileInputsRef.current[kind] = el
                    }}
                    type="file"
                    accept="image/*"
                    capture="environment"
                    multiple={multiPhotoKinds.includes(kind)}
                    onChange={(e) => void onFiles(kind, e.target.files, e.currentTarget)}
                  />
                  {isChecking ? 'Checking…' : 'Take photo or upload'}
                </label>
              </div>

              {isExpanded && (
                <div id={panelId} className="capture-slot-panel">
                  <h3 className="capture-slot-panel-title">{slot.label}</h3>
                  <div className="capture-slot-actions">
                    <WhyNeedTrigger
                      onActivate={(el) => {
                        whyNeedTriggerRef.current = el
                        setWhyNeedId(kind)
                      }}
                    />
                    <button
                      type="button"
                      className="btn capture-examples-trigger"
                      onClick={(e) => {
                        examplesTriggerRef.current = e.currentTarget
                        setExamplesKind(kind)
                      }}
                    >
                      See examples
                    </button>
                  </div>
                  <p className="capture-item-guidance">{CAPTURE_GUIDANCE[kind].oneLine}</p>
                  {CAPTURE_GUIDANCE[kind].detail && (
                    <p className="subtle capture-item-detail">{CAPTURE_GUIDANCE[kind].detail}</p>
                  )}
                  {photoErrors[kind] && (
                    <p className="error" role="alert">{photoErrors[kind]}</p>
                  )}
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

                  {kind === 'radiators' && (
                    <div className="video-capture-option">
                      <div className="video-capture-header">
                        <h4>Or film your radiators</h4>
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
              )}
            </li>
          )
        })}
      </ul>

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
    </section>
  )
}
