import { WHY_NEED, type WhyNeedId } from '../lib/captureWhyNeed'
import { AccessibleModalDialog } from './AccessibleModalDialog'

type Props = {
  id: WhyNeedId
  onClose: () => void
  returnFocusTo: HTMLElement | null
}

export function CaptureWhyNeedDialog({ id, onClose, returnFocusTo }: Props) {
  const content = WHY_NEED[id]

  return (
    <AccessibleModalDialog
      title={content.dialogTitle}
      onClose={onClose}
      returnFocusTo={returnFocusTo}
      overlayClassName="capture-examples-overlay"
      panelClassName="capture-examples-panel card capture-why-need-panel"
    >
      <ul className="capture-why-need-list">
        {content.bullets.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
      <p className="capture-why-need-privacy subtle">
        <strong>Privacy:</strong> {content.privacy}
      </p>
    </AccessibleModalDialog>
  )
}
