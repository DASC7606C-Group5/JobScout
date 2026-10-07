import { useController } from 'react-hook-form'

import { parseDirections, type ProfileFormValues } from '../../lib/profile-form'

export function DirectionField() {
  const { field } = useController<ProfileFormValues, 'directions'>({
    name: 'directions',
  })
  const selected = parseDirections(field.value)
  return (
    <div className="-mx-5 border-t border-base-300 px-5 pt-5 sm:-mx-6 sm:px-6 sm:pt-6">
      <div className="mb-3 flex items-center gap-2">
        <h2 className="text-sm font-semibold">Job preferences</h2>
      </div>
      <label htmlFor="directions" className="mb-2 block text-sm">
        Job directions <span className="ml-1 text-xs text-base-content/50">Optional</span>
      </label>
      <textarea
        id="directions"
        {...field}
        className="textarea field-sizing-content max-h-96 min-h-16 w-full resize-none border border-base-300 bg-base-200/25 text-sm leading-6"
        rows={2}
        placeholder={'Frontend development\nData analysis'}
        maxLength={300}
      />
      <div className="mt-2.5 flex flex-wrap gap-2">
        {['Frontend development', 'Data analysis', 'Product design', 'Software engineering'].map(
          (direction) => {
            const active = selected.includes(direction)
            return (
              <button
                type="button"
                key={direction}
                aria-pressed={active}
                className={`btn border font-normal shadow-none btn-xs ${active ? 'border-primary-content/20 bg-primary/20 text-primary-content' : 'border-base-300 bg-base-100 text-base-content/65'}`}
                onClick={() =>
                  field.onChange(
                    (active
                      ? selected.filter((value) => value !== direction)
                      : [...selected, direction]
                    ).join('\n'),
                  )
                }
              >
                {active ? '✓' : '+'} {direction}
              </button>
            )
          },
        )}
      </div>
    </div>
  )
}
