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
      <div className="mb-3 flex items-center justify-between gap-3 text-sm">
        <label htmlFor={id}>Jobs to show</label>
        <output htmlFor={id} className="font-medium tabular-nums">
          {value}
        </output>
      </div>
      <div>
        <input
          id={id}
          ref={inputRef}
          type="range"
          min={5}
          max={20}
          step={1}
          value={value}
          className="range w-full range-primary range-sm"
          disabled={disabled}
          aria-invalid={Boolean(error)}
          aria-describedby={error ? `${id}-hint` : undefined}
          onChange={(event) => onChange(event.target.valueAsNumber)}
        />
        <div className="mt-1 flex justify-between text-xs text-base-content/55" aria-hidden="true">
          <span>5</span>
          <span>20</span>
        </div>
      </div>
      {error && (
        <p id={`${id}-hint`} className="mt-2 text-xs text-error">
          {error}
        </p>
      )}
    </div>
  )
}
