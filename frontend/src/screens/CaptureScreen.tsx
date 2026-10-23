import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { ImageCoverUp } from '../components/ImageCoverUp'
import { VerificationLogPanel } from '../components/VerificationLog'
import { useSession } from '../context/SessionContext'
import { prepareImageFile } from '../lib/imagePrepare'
import { coverUpGuidance, coverUpTitle } from '../lib/photoGuidance'
import type { PhotoKind } from '../api'

type PendingCoverUp = {
  kind: PhotoKind
  url: string
  fileName: string
}

export function CaptureScreen() {
  const { photos, setPhotoResult, address } = useSession()
  const [busy, setBusy] = useState<Record<string, boolean>>({})
  const [pending, setPending] = useState<PendingCoverUp | null>(null)
  const [prepareError, setPrepareError] = useState<string | null>(null)

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
    setBusy((b) => ({ ...b, [kind]: true }))
    setPhotoResult(kind, null, redacted.name)
    try {
      const result = await api.checkPhoto(kind, redacted)
      setPhotoResult(kind, result, redacted.name)
    } catch {
      setPhotoResult(kind, null, redacted.name)
    } finally {
      setBusy((b) => ({ ...b, [kind]: false }))
    }
  }

  const readyCount = photos.filter((p) => p.result?.legible).length
  const showLog = readyCount >= 2

  return (
    <section className="screen capture-screen">
      <h1>Capture</h1>
      {address ? (
        <p className="subhead">{address.address}</p>
      ) : (
        <p className="warning">Pick an address on Start — using demo home for now.</p>
      )}

      <p className="lede">
        Use your camera or upload. Each photo is stripped of hidden metadata, you redact anything
        identifying, then we check it.
      </p>
      {prepareError && <p className="warning">{prepareError}</p>}

      <div className="photo-grid">
        {photos.map((slot) => (
          <div key={slot.kind} className="photo-slot card">
            <h2>{slot.label}</h2>
            <label className="upload-btn">
              <input
                type="file"
                accept="image/*"
                capture="environment"
                onChange={(e) => void onFile(slot.kind, e.target.files?.[0] ?? null)}
              />
              {busy[slot.kind] ? 'Checking…' : 'Take photo or upload'}
            </label>
            {slot.fileName && <p className="file-name">{slot.fileName}</p>}
            {slot.result && (
              <div className={`check-result ${slot.result.legible ? 'ok' : 'warn'}`}>
                <p>{slot.result.summary}</p>
                {slot.result.retake_hint && <p className="retake">{slot.result.retake_hint}</p>}
                {slot.result.privacy_warning && (
                  <p className="privacy-warn">{slot.result.privacy_warning}</p>
                )}
                {!slot.result.privacy_warning && slot.result.legible && (
                  <p className="privacy-ok">Redacted image only — no metadata stored.</p>
                )}
              </div>
            )}
          </div>
        ))}
      </div>

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

      <VerificationLogPanel visible={showLog} />

      <p className="cta-row">
        <Link className="btn primary" to="/estimates">
          Run estimates
        </Link>
      </p>
    </section>
  )
}
