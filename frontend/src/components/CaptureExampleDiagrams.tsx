import type { ReactNode } from 'react'
import type { PhotoKind } from '../api'

type Variant = 'good' | 'bad'

type Props = {
  kind: PhotoKind
  variant: Variant
}

function frame(children: ReactNode, variant: Variant) {
  const stroke = variant === 'good' ? 'var(--color-ok)' : 'var(--color-warn)'
  return (
    <svg viewBox="0 0 160 120" width="100%" height="auto" role="img" aria-hidden>
      <rect x="4" y="4" width="152" height="112" rx="8" fill="var(--surface-2)" stroke={stroke} strokeWidth="3" />
      {children}
    </svg>
  )
}

function BoilerDiagram({ variant }: { variant: Variant }) {
  if (variant === 'good') {
    return frame(
      <>
        <rect x="40" y="28" width="80" height="64" rx="4" fill="var(--bg)" stroke="var(--text-muted)" />
        <rect x="48" y="40" width="64" height="36" rx="2" fill="var(--surface-2)" stroke="var(--text-muted)" />
        <text x="80" y="58" textAnchor="middle" fontSize="8" fill="var(--text)">24 kW</text>
        <text x="80" y="70" textAnchor="middle" fontSize="7" fill="var(--text-muted)">make / model</text>
      </>,
      variant,
    )
  }
  return frame(
    <>
      <rect x="70" y="40" width="48" height="40" rx="4" fill="var(--bg)" stroke="var(--text-muted)" opacity="0.6" />
      <text x="80" y="95" textAnchor="middle" fontSize="8" fill="var(--text-muted)">too far</text>
      <path d="M20 30 L50 50" stroke="var(--color-warn)" strokeWidth="2" opacity="0.5" />
    </>,
    variant,
  )
}

function RadiatorDiagram({ variant }: { variant: Variant }) {
  if (variant === 'good') {
    return frame(
      <>
        <rect x="30" y="32" width="100" height="56" rx="3" fill="var(--bg)" stroke="var(--text-muted)" />
        {[0, 1, 2, 3, 4].map((i) => (
          <line
            key={i}
            x1={38 + i * 18}
            y1="36"
            x2={38 + i * 18}
            y2="84"
            stroke="var(--text-muted)"
            strokeWidth="2"
          />
        ))}
        <line x1="24" y1="92" x2="136" y2="92" stroke="var(--color-accent)" strokeWidth="2" />
        <text x="80" y="100" textAnchor="middle" fontSize="7" fill="var(--text-muted)">scale</text>
      </>,
      variant,
    )
  }
  return frame(
    <>
      <rect x="60" y="40" width="56" height="40" rx="3" fill="var(--bg)" stroke="var(--text-muted)" />
      <text x="80" y="95" textAnchor="middle" fontSize="8" fill="var(--text-muted)">cropped</text>
    </>,
    variant,
  )
}

function FuseDiagram({ variant }: { variant: Variant }) {
  if (variant === 'good') {
    return frame(
      <>
        <rect x="52" y="36" width="56" height="48" rx="4" fill="var(--bg)" stroke="var(--text-muted)" />
        <text x="80" y="64" textAnchor="middle" fontSize="14" fontWeight="bold" fill="var(--text)">80A</text>
        <text x="80" y="78" textAnchor="middle" fontSize="7" fill="var(--text-muted)">fuse carrier</text>
      </>,
      variant,
    )
  }
  return frame(
    <>
      <rect x="40" y="44" width="80" height="32" rx="4" fill="var(--bg)" stroke="var(--text-muted)" />
      <text x="80" y="64" textAnchor="middle" fontSize="8" fill="var(--text-muted)">consumer unit</text>
    </>,
    variant,
  )
}

function OutdoorDiagram({ variant }: { variant: Variant }) {
  if (variant === 'good') {
    return frame(
      <>
        <rect x="20" y="70" width="120" height="24" fill="var(--surface-2)" />
        <rect x="28" y="48" width="48" height="22" fill="var(--bg)" stroke="var(--text-muted)" />
        <rect x="88" y="52" width="40" height="18" fill="var(--bg)" stroke="var(--text-muted)" />
        <line x1="24" y1="88" x2="100" y2="88" stroke="var(--color-accent)" strokeWidth="2" />
      </>,
      variant,
    )
  }
  return frame(
    <>
      <rect x="50" y="50" width="60" height="40" fill="var(--bg)" stroke="var(--text-muted)" />
      <text x="80" y="105" textAnchor="middle" fontSize="8" fill="var(--text-muted)">no context</text>
    </>,
    variant,
  )
}

function BillDiagram({ variant }: { variant: Variant }) {
  if (variant === 'good') {
    return frame(
      <>
        <rect x="36" y="28" width="88" height="64" rx="2" fill="var(--bg)" stroke="var(--text-muted)" />
        <text x="80" y="48" textAnchor="middle" fontSize="7" fill="var(--text-muted)">████████</text>
        <text x="80" y="62" textAnchor="middle" fontSize="9" fill="var(--text)">12,400 kWh</text>
        <text x="80" y="76" textAnchor="middle" fontSize="8" fill="var(--text)">1 Apr – 31 Mar</text>
      </>,
      variant,
    )
  }
  return frame(
    <>
      <rect x="36" y="28" width="88" height="64" rx="2" fill="var(--bg)" stroke="var(--text-muted)" />
      <text x="80" y="52" textAnchor="middle" fontSize="9" fill="var(--text)">£142.00</text>
      <text x="80" y="68" textAnchor="middle" fontSize="8" fill="var(--text-muted)">no kWh / dates</text>
      <text x="80" y="82" textAnchor="middle" fontSize="7" fill="var(--color-warn)">name visible</text>
    </>,
    variant,
  )
}

const DIAGRAMS: Record<PhotoKind, (p: { variant: Variant }) => ReactNode> = {
  boiler_plate: BoilerDiagram,
  radiators: RadiatorDiagram,
  fuse_cutout: FuseDiagram,
  outdoor_space: OutdoorDiagram,
  gas_bill: BillDiagram,
}

export function CaptureExampleDiagram({ kind, variant }: Props) {
  const Draw = DIAGRAMS[kind]
  return <div className={`capture-example-diagram capture-example-diagram--${variant}`}>{Draw({ variant })}</div>
}
