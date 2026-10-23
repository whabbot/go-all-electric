import type { RadiatorVideoResult } from '../api'

const STATUS_LABELS: Record<string, string> = {
  verified: 'verified',
  verified_with_warnings: 'verified, with warnings',
  couldnt_tell: "couldn't tell",
}

const UPSIZE_LABELS: Record<string, string> = {
  ok: 'ok',
  marginal: 'marginal',
  upsize: 'upsize',
  couldnt_tell: "couldn't tell",
}

export function RadiatorVideoResults({ result }: { result: RadiatorVideoResult }) {
  return (
    <div className={`check-result video-result ${result.status === 'couldnt_tell' ? 'warn' : 'ok'}`}>
      <p className="video-result-summary">
        <strong>
          {result.radiator_count} radiator{result.radiator_count === 1 ? '' : 's'} spotted
        </strong>
        <span className={`reading-status ${result.status}`}>
          {STATUS_LABELS[result.status] ?? result.status}
        </span>{' '}
        <span className="subtle">
          ({result.model}
          {result.attempts > 1 ? ', after a re-read' : ''})
        </span>
      </p>

      {result.radiators.length > 0 && (
        <ul className="radiator-list video-radiator-list">
          {result.radiators.map((r, i) => {
            const label = r.room || `Radiator ${i + 1}`
            const timestamp = r.last_seen ? `${r.first_seen}–${r.last_seen}` : r.first_seen
            const typeText = r.radiator_type
              ? `${r.radiator_type.replaceAll('_', ' ')}${
                  r.panels != null && r.fin_rows != null ? ` (${r.panels}P/${r.fin_rows}F)` : ''
                }`
              : "type couldn't tell"
            const sizeText =
              r.height_mm != null && r.width_mm != null
                ? `${r.height_mm} × ${r.width_mm} mm`
                : "size couldn't tell"

            return (
              <li key={`${r.first_seen}-${i}`} className={`rad-${r.upsize_status}`}>
                <div className="video-rad-head">
                  <span className="video-rad-time">{timestamp}</span>
                  <strong>{label}</strong>
                  <span className={`status-pill status-${r.upsize_status}`}>
                    {UPSIZE_LABELS[r.upsize_status] ?? r.upsize_status}
                  </span>
                  <span className={`conf conf-${r.confidence}`}>{r.confidence}</span>
                </div>
                <p className="video-rad-spec">
                  Type: <strong>{typeText}</strong> · Size: <strong>{sizeText}</strong>
                </p>
                {r.output_at_flow_temp_w != null && r.heat_loss_w != null && (
                  <p className="subtle">
                    At 45°C: {Math.round(r.output_at_flow_temp_w)} W output vs{' '}
                    {Math.round(r.heat_loss_w)} W room share
                    {r.upsize_status === 'upsize' && r.required_output_dt50_w != null
                      ? ` · consider ~${Math.round(r.required_output_dt50_w)} W (ΔT50)`
                      : ''}
                  </p>
                )}
                {r.could_not_judge.length > 0 && (
                  <p className="subtle">Could not judge: {r.could_not_judge.join('; ')}</p>
                )}
                {r.photo_request && <p className="retake">{r.photo_request}</p>}
              </li>
            )
          })}
        </ul>
      )}

      {result.photo_requests.length > 0 && (
        <div className="video-photo-requests">
          <p className="retake">
            <strong>Photo requests:</strong>
          </p>
          <ul>
            {result.photo_requests.map((req, i) => (
              <li key={i} className="retake">
                {req}
              </li>
            ))}
          </ul>
        </div>
      )}

      <p className="privacy-ok">
        Container metadata (GPS, device, timestamps) stripped server-side — video never stored.
      </p>
    </div>
  )
}
