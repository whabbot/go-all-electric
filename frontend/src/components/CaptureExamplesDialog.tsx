import { useEffect, useId, useRef } from 'react'
import type { PhotoKind } from '../api'
import { CAPTURE_GUIDANCE } from '../lib/captureGuide'
import { CaptureExampleDiagram } from './CaptureExampleDiagrams'

const FOCUSABLE =
  'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

type Props = {
  kind: PhotoKind
  title: string
  onClose: () => void
  returnFocusTo: HTMLElement | null
}

export function CaptureExamplesDialog({ kind, title, onClose, returnFocusTo }: Props) {
  const titleId = useId()
  const panelRef = useRef<HTMLDivElement>(null)
  const closeRef = useRef<HTMLButtonElement>(null)
  const guidance = CAPTURE_GUIDANCE[kind]

  useEffect(() => {
    const previouslyFocused = document.activeElement as HTMLElement | null
    closeRef.current?.focus()

    const panel = panelRef.current
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        onClose()
        return
      }
      if (event.key !== 'Tab' || !panel) return
      const nodes = [...panel.querySelectorAll<HTMLElement>(FOCUSABLE)]
      if (nodes.length === 0) return
      const first = nodes[0]
      const last = nodes[nodes.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }

    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      const target = returnFocusTo ?? previouslyFocused
      target?.focus()
    }
  }, [onClose, returnFocusTo])

  return (
    <div className="capture-examples-overlay" onClick={onClose}>
      <div
        ref={panelRef}
        className="capture-examples-panel card"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="capture-examples-header">
          <h2 id={titleId}>Example photos: {title}</h2>
          <button ref={closeRef} type="button" className="btn capture-examples-close" onClick={onClose}>
            Close
          </button>
        </div>
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
      </div>
    </div>
  )
}
