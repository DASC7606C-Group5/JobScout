import type { Ref } from 'react'

import { resultCountError } from '../../lib/profile-form'

export function ResultCountField({
  id,
  value,
  onChange,
  inputRef,
  disabled = false,
}: {
  id: string
  value: number
  onChange: (value: number) => void
  inputRef?: Ref<HTMLInputElement>
  disabled?: boolean
}) {
  const error = resultCountError(value)
  return (
    <div>
      <label htmlFor={id} className="mb-2 block text-sm">
        Matching jobs to find
      </label>
      <div className="flex items-center gap-4">
        <input
          id={`${id}-range`}
          type="range"
          min={5}
          max={20}
          step={1}
          className="range min-w-0 flex-1 range-sm"
          aria-label="Matching jobs to find slider"
          aria-describedby={error ? `${id}-hint` : undefined}
          value={Math.min(20, Math.max(5, value))}
          disabled={disabled}
          onChange={(event) => onChange(event.target.valueAsNumber)}
        />
        <input
          id={id}
          ref={inputRef}
          type="number"
          min={5}
          max={20}
          step={1}
          value={value || ''}
          className="input w-24 border border-base-300 bg-base-200/25 text-sm"
          disabled={disabled}
          aria-invalid={Boolean(error)}
          aria-describedby={error ? `${id}-hint` : undefined}
          onChange={(event) => onChange(event.target.value === '' ? 0 : event.target.valueAsNumber)}
        />
      </div>
      {error && (
        <p id={`${id}-hint`} className="mt-2 text-xs text-error">
          {error}
        </p>
      )}
    </div>
  )
}
