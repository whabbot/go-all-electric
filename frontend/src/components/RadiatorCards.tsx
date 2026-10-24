import { useEffect, useId, useRef } from 'react'
import { MAX_PHOTOS_PER_RADIATOR, MAX_RADIATORS, type RadiatorCard } from '../context/SessionContext'
import { RADIATOR_NOTE_MAX, RADIATOR_ROOMS, radiatorLabel, type DetailInputs } from '../lib/knownDetails'
import { RadiatorDetails } from './KnownDetails'

type Props = {
  radiators: RadiatorCard[]
  /** The card just added: it is scrolled into view with its Room picker focused. */
  focusId?: string | null
  photoErrors: Record<string, string>
  onAddRadiator: () => void
  onRemoveRadiator: (id: string) => void
  onLabelChange: (id: string, patch: { room?: string; note?: string }) => void
  onDetailsChange: (id: string, details: DetailInputs) => void
  onAddPhotos: (id: string, list: FileList | null, input: HTMLInputElement) => void
  onRetakePhoto: (id: string, photoId: string, list: FileList | null, input: HTMLInputElement) => void
  onRemovePhoto: (id: string, photoId: string) => void
}

function RadiatorCardItem({
  card,
  number,
  error,
  focus,
  ...actions
}: Omit<Props, 'radiators' | 'photoErrors' | 'onAddRadiator' | 'focusId'> & {
  card: RadiatorCard
  number: number
  error?: string
  focus: boolean
}) {
  const id = useId()
  const roomRef = useRef<HTMLSelectElement>(null)
  useEffect(() => {
    if (!focus || !roomRef.current) return
    roomRef.current.scrollIntoView?.({ block: 'center' })
    roomRef.current.focus({ preventScroll: true })
  }, [focus])
  const name = `Radiator ${number}`
  const label = radiatorLabel(card.room, card.note)
  const full = card.photos.length >= MAX_PHOTOS_PER_RADIATOR
  return (
    <li className="radiator-card" aria-labelledby={`${id}-title`}>
      <div className="radiator-card-header">
        <h3 id={`${id}-title`}>
          {name}
          {label && <span className="radiator-card-label"> · {label}</span>}
        </h3>
        <button
          type="button"
          className="btn"
          aria-label={`Remove ${name}`}
          onClick={() => actions.onRemoveRadiator(card.id)}
        >
          Remove
        </button>
      </div>

      <div className="known-field-row">
        <div className="known-field">
          <label htmlFor={`${id}-room`}>Room</label>
          <select
            ref={roomRef}
            id={`${id}-room`}
            value={card.room}
            onChange={(e) => actions.onLabelChange(card.id, { room: e.target.value })}
          >
            <option value="">Pick a room</option>
            {RADIATOR_ROOMS.map((room) => (
              <option key={room} value={room}>
                {room}
              </option>
            ))}
          </select>
        </div>
        <div className="known-field">
          <label htmlFor={`${id}-note`}>Note (optional)</label>
          <input
            id={`${id}-note`}
            type="text"
            maxLength={RADIATOR_NOTE_MAX}
            autoComplete="off"
            placeholder="e.g. under the window"
            value={card.note}
            onChange={(e) => actions.onLabelChange(card.id, { note: e.target.value })}
          />
        </div>
      </div>
      <p className="subtle radiator-card-privacy">Labels are for you: they stay on this device and are never sent to Gemini.</p>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {card.photos.length > 0 && (
        <ul className="radiator-list" aria-label={`Photos of ${name}`}>
          {card.photos.map((photo, idx) => {
            const photoName = `${name} photo ${idx + 1}`
            return (
              <li key={photo.id} className="radiator-photo-item">
                <img
                  src={photo.previewUrl}
                  alt={`${photoName} preview`}
                  width={96}
                  height={72}
                  className="radiator-photo-thumb"
                />
                <div className="radiator-photo-body">
                  <p>
                    <strong>Photo {idx + 1}</strong> <span className="subtle">({photo.fileName})</span>
                  </p>
                  {photo.checking && <p className="subtle">Checking…</p>}
                  {photo.error && (
                    <p className="error" role="alert">
                      {photo.error}
                    </p>
                  )}
                  {photo.result && (
                    <div className={`check-result ${photo.result.legible ? 'ok' : 'warn'}`}>
                      <p>
                        {photo.result.summary}{' '}
                        <span className="subtle">
                          ({photo.result.model}, {(photo.result.elapsed_ms / 1000).toFixed(1)}s)
                        </span>
                      </p>
                      {!photo.result.matches_expected && (
                        <p className="retake">
                          {photo.result.kind === 'other'
                            ? "This doesn't look like a radiator."
                            : `This looks like a ${photo.result.kind.replaceAll('_', ' ')}.`}
                        </p>
                      )}
                      {photo.result.retake_hint && <p className="retake">{photo.result.retake_hint}</p>}
                      {photo.result.privacy_warning && <p className="privacy-warn">{photo.result.privacy_warning}</p>}
                      {!photo.result.privacy_warning && photo.result.legible && (
                        <p className="privacy-ok">Redacted image only — no metadata stored.</p>
                      )}
                    </div>
                  )}
                  <div className="capture-slot-actions">
                    <label className="btn upload-btn">
                      <input
                        type="file"
                        accept="image/*"
                        capture="environment"
                        aria-label={`Retake ${photoName}`}
                        onChange={(e) => actions.onRetakePhoto(card.id, photo.id, e.target.files, e.currentTarget)}
                      />
                      Retake
                    </label>
                    <button
                      type="button"
                      className="btn"
                      aria-label={`Remove ${photoName}`}
                      onClick={() => actions.onRemovePhoto(card.id, photo.id)}
                    >
                      Remove
                    </button>
                  </div>
                </div>
              </li>
            )
          })}
        </ul>
      )}
      {!full && (
        <label className="btn upload-btn radiator-card-add-photo">
          <input
            type="file"
            accept="image/*"
            capture="environment"
            multiple
            aria-label={`Add photos of ${name}`}
            onChange={(e) => actions.onAddPhotos(card.id, e.target.files, e.currentTarget)}
          />
          {card.photos.length === 0 ? 'Take photo or upload' : 'Add another photo of this radiator'}
        </label>
      )}
      <p className="subtle">
        {card.photos.length === 0
          ? `Up to ${MAX_PHOTOS_PER_RADIATOR} photos of this one radiator, or just add the details you know.`
          : `${card.photos.length} of ${MAX_PHOTOS_PER_RADIATOR} photos: all read together as this one radiator.`}
      </p>

      <RadiatorDetails inputs={card.details} onChange={(next) => actions.onDetailsChange(card.id, next)} />
    </li>
  )
}

/** One card per radiator: its label, its photos (read together), and details the homeowner knows. */
export function RadiatorCards({ radiators, photoErrors, onAddRadiator, focusId, ...actions }: Props) {
  return (
    <div className="radiator-cards">
      {radiators.length > 0 && (
        <ol className="radiator-card-list" aria-label="Your radiators">
          {radiators.map((card, i) => (
            <RadiatorCardItem
              key={card.id}
              card={card}
              number={i + 1}
              error={photoErrors[`radiators:${card.id}`]}
              focus={card.id === focusId}
              {...actions}
            />
          ))}
        </ol>
      )}
      {radiators.length < MAX_RADIATORS ? (
        <button type="button" className="btn primary radiator-add" onClick={onAddRadiator}>
          + Add radiator
        </button>
      ) : (
        <p className="subtle">That&apos;s the most we check ({MAX_RADIATORS} radiators).</p>
      )}
    </div>
  )
}
