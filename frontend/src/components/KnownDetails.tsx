import { useId, type ReactNode } from 'react'
import {
  FUSE_RATINGS_A,
  RADIATOR_SHAPES,
  RADIATOR_TYPE_OPTIONS,
  parseKnownBoiler,
  parseKnownRadiator,
  type DetailInputs,
} from '../lib/knownDetails'
import type { RadiatorKind } from '../api'

type FieldsProps = {
  inputs: DetailInputs
  onChange: (next: DetailInputs) => void
}

/** Collapsed by default: the photo does the work; this is for anyone who already knows. */
function Expander({ count, children }: { count: number; children: ReactNode }) {
  return (
    <details className="known-details">
      <summary>
        Add details you know
        {count > 0 && <span className="known-details-count">{count} added</span>}
      </summary>
      <div className="known-details-body">
        <p className="subtle">
          Optional. Anything you enter is used instead of what we read from the photo, and if the photo
          disagrees we show you both.
        </p>
        {children}
      </div>
    </details>
  )
}

function TextField({
  field,
  label,
  hint,
  inputs,
  onChange,
  error,
  inputMode,
  maxLength,
  unit,
}: {
  field: string
  label: string
  hint?: string
  inputs: DetailInputs
  onChange: (next: DetailInputs) => void
  error?: string
  inputMode?: 'numeric' | 'decimal' | 'text'
  maxLength?: number
  unit?: string
}) {
  const id = useId()
  return (
    <div className={`known-field${error ? ' known-field--error' : ''}`}>
      <label htmlFor={id}>{label}</label>
      <div className="known-field-input">
        <input
          id={id}
          type="text"
          inputMode={inputMode}
          maxLength={maxLength}
          autoComplete="off"
          value={inputs[field] ?? ''}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? `${id}-error` : hint ? `${id}-hint` : undefined}
          onChange={(e) => onChange({ ...inputs, [field]: e.target.value })}
        />
        {unit && <span className="known-field-unit">{unit}</span>}
      </div>
      {error ? (
        <p id={`${id}-error`} className="error known-field-message">
          {error}
        </p>
      ) : (
        hint && (
          <p id={`${id}-hint`} className="subtle known-field-message">
            {hint}
          </p>
        )
      )}
    </div>
  )
}

export function RadiatorDetails({ inputs, onChange }: FieldsProps) {
  const { known, errors } = parseKnownRadiator(inputs)
  const typeId = useId()
  const type = inputs.radiator_type as RadiatorKind | undefined
  const option = RADIATOR_TYPE_OPTIONS.find((o) => o.value === type)
  const shape = type ? RADIATOR_SHAPES[type] : undefined
  return (
    <Expander count={Object.keys(known).length}>
      <div className="known-field">
        <label htmlFor={typeId}>Type</label>
        <select
          id={typeId}
          value={type ?? ''}
          aria-describedby={`${typeId}-hint`}
          onChange={(e) => onChange({ ...inputs, radiator_type: e.target.value })}
        >
          <option value="">Not sure</option>
          {RADIATOR_TYPE_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        <p id={`${typeId}-hint`} className="subtle known-field-message">
          {option
            ? `${option.hint}.${shape ? ` That's ${shape[0]} panel${shape[0] === 1 ? '' : 's'} and ${shape[1]} fin row${shape[1] === 1 ? '' : 's'}.` : ''}`
            : 'Look down at the top grille: count the flat panels, and the zig-zag fin rows between or behind them.'}
        </p>
      </div>
      <div className="known-field-row">
        <TextField
          field="panels"
          label="Panels"
          inputs={inputs}
          onChange={onChange}
          error={errors.panels}
          inputMode="numeric"
          maxLength={1}
        />
        <TextField
          field="fin_rows"
          label="Fin rows (grilles)"
          inputs={inputs}
          onChange={onChange}
          error={errors.fin_rows}
          inputMode="numeric"
          maxLength={1}
        />
      </div>
      <div className="known-field-row">
        <TextField
          field="width_mm"
          label="Width"
          hint="End to end, not counting pipes"
          inputs={inputs}
          onChange={onChange}
          error={errors.width_mm}
          inputMode="numeric"
          maxLength={4}
          unit="mm"
        />
        <TextField
          field="height_mm"
          label="Height"
          hint="Top to bottom of the panel"
          inputs={inputs}
          onChange={onChange}
          error={errors.height_mm}
          inputMode="numeric"
          maxLength={4}
          unit="mm"
        />
      </div>
    </Expander>
  )
}

export function BoilerDetails({ inputs, onChange }: FieldsProps) {
  const { known, errors } = parseKnownBoiler(inputs)
  return (
    <Expander count={Object.keys(known).length}>
      <div className="known-field-row">
        <TextField field="make" label="Make" hint="e.g. Worcester Bosch" inputs={inputs} onChange={onChange} error={errors.make} maxLength={40} />
        <TextField field="model" label="Model" hint="e.g. Greenstar 30i" inputs={inputs} onChange={onChange} error={errors.model} maxLength={60} />
      </div>
      <div className="known-field-row">
        <TextField
          field="heating_output_kw"
          label="Heating output"
          hint="Central heating, from the plate or manual"
          inputs={inputs}
          onChange={onChange}
          error={errors.heating_output_kw}
          inputMode="decimal"
          maxLength={5}
          unit="kW"
        />
        <TextField
          field="hot_water_output_kw"
          label="Hot-water output"
          hint="Combi boilers only"
          inputs={inputs}
          onChange={onChange}
          error={errors.hot_water_output_kw}
          inputMode="decimal"
          maxLength={5}
          unit="kW"
        />
      </div>
    </Expander>
  )
}

export function FuseDetails({ inputs, onChange }: FieldsProps) {
  const id = useId()
  return (
    <Expander count={inputs.rating_a ? 1 : 0}>
      <div className="known-field">
        <label htmlFor={id}>Main fuse rating</label>
        <select
          id={id}
          value={inputs.rating_a ?? ''}
          aria-describedby={`${id}-hint`}
          onChange={(e) => onChange({ ...inputs, rating_a: e.target.value })}
        >
          <option value="">Not sure</option>
          {FUSE_RATINGS_A.map((a) => (
            <option key={a} value={String(a)}>
              {a} A
            </option>
          ))}
        </select>
        <p id={`${id}-hint`} className="subtle known-field-message">
          The number on the sealed fuse carrier next to your meter.
        </p>
      </div>
    </Expander>
  )
}
