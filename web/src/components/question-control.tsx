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
  return (
    <fieldset
      className="min-w-0 rounded-xl border border-base-300 p-4"
      aria-describedby={`${id}-reason`}
    >
      <legend className="px-1 text-sm font-medium">
        {question.question} · {question.required ? '必填' : '选填'}
      </legend>
      <p id={`${id}-reason`} className="mb-3 text-xs text-base-content/60">
        {question.reason}
      </p>
      <fieldset disabled={skipped} className="space-y-2">
        {question.control_type === 'text' ? (
          <input
            id={id}
            aria-label={question.question}
            className="input w-full"
            value={typeof value === 'string' ? value : ''}
            maxLength={2000}
            onChange={(event) => onChange(event.target.value)}
          />
        ) : (
          question.options.map((option) => {
            const multiple = question.control_type === 'multiple_choice'
            const selected = Array.isArray(value) ? value : []
            return (
              <label key={option.id} className="flex cursor-pointer items-center gap-3 text-sm">
                <input
                  type={multiple ? 'checkbox' : 'radio'}
                  name={id}
                  value={option.id}
                  className={multiple ? 'checkbox checkbox-sm' : 'radio radio-sm'}
                  checked={multiple ? selected.includes(option.id) : value === option.id}
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
                {option.label}
              </label>
            )
          })
        )}
      </fieldset>
      {!question.required && (
        <label className="mt-4 flex cursor-pointer items-center gap-2 text-xs text-base-content/65">
          <input
            type="checkbox"
            className="checkbox checkbox-xs"
            checked={skipped}
            onChange={(event) => onSkip(event.target.checked)}
          />
          跳过此问题
        </label>
      )}
    </fieldset>
  )
}
