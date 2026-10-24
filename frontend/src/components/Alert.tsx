import type { ReactNode } from 'react'

type AlertVariant = 'info' | 'success' | 'warn' | 'error'

const ICON: Record<AlertVariant, string> = {
  info: 'ℹ️',
  success: '✓',
  warn: '⚠',
  error: '✕',
}

type Props = {
  variant: AlertVariant
  title?: string
  children: ReactNode
  action?: ReactNode
}

export function Alert({ variant, title, children, action }: Props) {
  const role = variant === 'error' ? 'alert' : 'status'
  return (
    <div className={`alert alert-${variant}`} role={role}>
      <span className="alert-icon" aria-hidden="true">{ICON[variant]}</span>
      <div className="alert-body">
        {title && <strong className="alert-title">{title}</strong>}
        <div className="alert-message">{children}</div>
        {action && <div className="alert-action">{action}</div>}
      </div>
    </div>
  )
}
