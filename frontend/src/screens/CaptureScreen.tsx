import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { VerificationLogPanel } from '../components/VerificationLog'
import { useSession } from '../context/SessionContext'

export function CaptureScreen() {
  const { photos, setPhotoResult, address } = useSession()
  const [busy, setBusy] = useState<Record<string, boolean>>({})

  const onFile = async (kind: typeof photos[number]['kind'], file: File | null) => {
    if (!file) return
    setBusy((b) => ({ ...b, [kind]: true }))
    setPhotoResult(kind, null, file.name)
    try {
      const result = await api.checkPhoto(kind, file)
      setPhotoResult(kind, result, file.name)
    } catch {
      setPhotoResult(kind, null, file.name)
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

      <p className="lede">Use your camera or upload. Each photo is checked immediately.</p>

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
                  <p className="privacy-ok">No faces or number plates stored.</p>
                )}
              </div>
            )}
          </div>
        ))}
      </div>

      <VerificationLogPanel visible={showLog} />

      <p className="cta-row">
        <Link className="btn primary" to="/estimates">
          Run estimates
        </Link>
      </p>
    </section>
  )
}
