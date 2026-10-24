type Props = {
  onActivate: (button: HTMLButtonElement) => void
  className?: string
}

export function WhyNeedTrigger({ onActivate, className }: Props) {
  return (
    <button
      type="button"
      className={className ?? 'btn capture-why-need-trigger'}
      onClick={(e) => onActivate(e.currentTarget)}
    >
      Why do we need this?
    </button>
  )
}
