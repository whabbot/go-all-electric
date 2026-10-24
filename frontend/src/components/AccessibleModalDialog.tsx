import { useEffect, useId, useRef, type ReactNode } from 'react'

const FOCUSABLE =
  'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

type Props = {
  title: string
  labelledBy?: string
  onClose: () => void
  returnFocusTo: HTMLElement | null
  overlayClassName: string
  panelClassName: string
  headerClassName?: string
  closeButtonClassName?: string
  children: ReactNode
}

export function AccessibleModalDialog({
  title,
  labelledBy,
  onClose,
  returnFocusTo,
  overlayClassName,
  panelClassName,
  headerClassName,
  closeButtonClassName,
  children,
}: Props) {
  const defaultTitleId = useId()
  const titleId = labelledBy ?? defaultTitleId
  const panelRef = useRef<HTMLDivElement>(null)
  const closeRef = useRef<HTMLButtonElement>(null)

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
    <div className={overlayClassName} onClick={onClose}>
      <div
        ref={panelRef}
        className={panelClassName}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onClick={(e) => e.stopPropagation()}
      >
        <div className={headerClassName ?? 'capture-examples-header'}>
          <h2 id={titleId}>{title}</h2>
          <button
            ref={closeRef}
            type="button"
            className={closeButtonClassName ?? 'btn capture-examples-close'}
            onClick={onClose}
          >
            Close
          </button>
        </div>
        {children}
      </div>
    </div>
  )
}
