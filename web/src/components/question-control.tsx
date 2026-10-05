import type { ClarificationMessage } from '../lib/contracts'

export function QuestionControl({
  question,
  value,
  skipped,
  onChange,
  onSkip,
}: {
  question: ClarificationMessage
  value: string | string[]
  skipped: boolean
  onChange: (value: string | string[]) => void
  onSkip: (checked: boolean) => void
}) {
  const id = `question-${question.question_id}`
  const multiple = question.control_type === 'multiple_choice'
  const selected = Array.isArray(value) ? value : []
  const selectedIds = new Set(selected)
  const limitDirections = multiple && question.field === 'target_directions'
  return (
    <fieldset
      className="fieldset min-w-0 gap-3"
      aria-describedby={`${id}-reason${limitDirections ? ` ${id}-limit` : ''}`}
    >
      <legend className="fieldset-legend flex flex-wrap items-center gap-2 text-sm">
        {question.question}
        <span className="badge border-0 bg-base-200 text-xs badge-sm font-normal text-base-content/60">
          {question.required ? 'Required' : 'Optional'}
        </span>
      </legend>
      <p
        id={`${id}-reason`}
        className="label block text-xs leading-6 whitespace-normal text-base-content/60"
      >
        {question.reason}
      </p>
      {limitDirections && (
        <p id={`${id}-limit`} className="text-xs text-base-content/55">
          Choose up to three directions · {selected.length} / 3 selected
        </p>
      )}
      <fieldset disabled={skipped} className="grid min-w-0 gap-2 sm:grid-cols-2">
        {question.control_type === 'text' ? (
          <input
            id={id}
            aria-label={question.question}
            className="input w-full border border-base-300 bg-base-200/25 text-sm sm:col-span-2"
            value={typeof value === 'string' ? value : ''}
            maxLength={2000}
            onChange={(event) => onChange(event.target.value)}
          />
        ) : (
          question.options.map((option) => {
            const checked = multiple ? selectedIds.has(option.id) : value === option.id
            const disabled = limitDirections && selected.length >= 3 && !checked
            return (
              <label
                key={option.id}
                className={`flex min-w-0 items-center gap-3 rounded-selector border p-3 text-sm transition-colors ${checked ? 'border-base-content/25 bg-base-200/65' : 'border-base-300 bg-base-100'} ${disabled || skipped ? 'cursor-default opacity-55' : 'cursor-pointer hover:bg-base-200/40'}`}
              >
                <input
                  type={multiple ? 'checkbox' : 'radio'}
                  name={id}
                  value={option.id}
                  className={multiple ? 'checkbox shrink-0 checkbox-sm' : 'radio shrink-0 radio-sm'}
                  checked={checked}
                  disabled={disabled}
                  onChange={(event) =>
                    onChange(
                      multiple
                        ? event.target.checked
                          ? [...selected, option.id]
                          : selected.filter((item) => item !== option.id)
                        : option.id,
                    )
                  }
                />
                <span className="min-w-0 break-words">{option.label}</span>
              </label>
            )
          })
        )}
      </fieldset>
      {!question.required && (
        <label className="mt-1 flex w-fit cursor-pointer items-center gap-2 text-xs text-base-content/65">
          <input
            type="checkbox"
            className="checkbox checkbox-xs"
            checked={skipped}
            onChange={(event) => onSkip(event.target.checked)}
          />
          Skip this question
        </label>
      )}
    </fieldset>
  )
}
