import type { PhotoKind } from '../api'
import { CAPTURE_GUIDANCE } from '../lib/captureGuide'
import { AccessibleModalDialog } from './AccessibleModalDialog'
import { CaptureExampleDiagram } from './CaptureExampleDiagrams'

type Props = {
  kind: PhotoKind
  title: string
  onClose: () => void
  returnFocusTo: HTMLElement | null
}

export function CaptureExamplesDialog({ kind, title, onClose, returnFocusTo }: Props) {
  const guidance = CAPTURE_GUIDANCE[kind]

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
          <CaptureExampleDiagram kind={kind} variant="good" />
          <figcaption>
            <strong>Good</strong> — {guidance.goodReason}
          </figcaption>
        </figure>
        <figure>
          <CaptureExampleDiagram kind={kind} variant="bad" />
          <figcaption>
            <strong>Avoid</strong> — {guidance.badReason}
          </figcaption>
        </figure>
      </div>
    </AccessibleModalDialog>
  )
}
