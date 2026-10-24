import type { PhotoKind } from '../api'
import { CAPTURE_EXAMPLES } from '../lib/captureExamples'
import { CAPTURE_GUIDANCE } from '../lib/captureGuide'
import { AccessibleModalDialog } from './AccessibleModalDialog'

type Props = {
  kind: PhotoKind
  title: string
  onClose: () => void
  returnFocusTo: HTMLElement | null
}

export function CaptureExamplesDialog({ kind, title, onClose, returnFocusTo }: Props) {
  const guidance = CAPTURE_GUIDANCE[kind]
  const examples = CAPTURE_EXAMPLES[kind]

  return (
    <AccessibleModalDialog
      title={`Example photos: ${title}`}
      onClose={onClose}
      returnFocusTo={returnFocusTo}
      overlayClassName="capture-examples-overlay"
      panelClassName="capture-examples-panel card"
    >
      <div className="capture-examples-grid">
        <figure>
          <img
            className="capture-example-photo"
            src={examples.good.src}
            alt={examples.good.alt}
            width="800"
            height="600"
            loading="lazy"
            decoding="async"
          />
          <figcaption>
            <strong>Good</strong> — {guidance.goodReason}
            <span className="capture-example-illustration">Illustration · fictional example</span>
          </figcaption>
        </figure>
        <figure>
          <img
            className="capture-example-photo"
            src={examples.bad.src}
            alt={examples.bad.alt}
            width="800"
            height="600"
            loading="lazy"
            decoding="async"
          />
          <figcaption>
            <strong>Avoid</strong> — {guidance.badReason}
            <span className="capture-example-illustration">Illustration · fictional example</span>
          </figcaption>
        </figure>
      </div>
    </AccessibleModalDialog>
  )
}
