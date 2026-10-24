import { CAPTURE_STATUS_LABEL, CAPTURE_SUMMARY_ITEMS } from '../lib/captureGuide'

export function CaptureGuideSummary() {
  return (
    <aside className="capture-guide-summary card" aria-labelledby="capture-guide-heading">
      <h2 id="capture-guide-heading">What you&apos;ll need</h2>
      <p className="subtle capture-guide-intro">
        About 5–10 minutes total. Each photo is checked after you redact anything identifying.
      </p>
      <ul className="capture-guide-list">
        {CAPTURE_SUMMARY_ITEMS.map((item) => (
          <li key={item.id}>
            <span className="capture-guide-label">{item.label}</span>
            <span className={`capture-guide-status capture-guide-status--${item.status}`}>
              {CAPTURE_STATUS_LABEL[item.status]}
            </span>
            {item.reason ? (
              <span className="capture-guide-reason subtle">{item.reason}</span>
            ) : null}
            <span className="capture-guide-meta">
              {item.photoCount} · {item.timeHint}
            </span>
          </li>
        ))}
      </ul>
    </aside>
  )
}
