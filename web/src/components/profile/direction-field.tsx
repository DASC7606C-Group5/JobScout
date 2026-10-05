import { useController } from 'react-hook-form'

import { parseDirections, type ProfileFormValues } from '../../lib/profile-form'
import { Icon } from '../icon'

export function DirectionField() {
  const { field, fieldState } = useController<ProfileFormValues, 'directions'>({
    name: 'directions',
    rules: {
      validate: (value) =>
        parseDirections(value).length <= 3 || 'Choose no more than three job directions.',
    },
  })
  const selected = parseDirections(field.value)
  return (
    <div className="border-t border-base-300 pt-6">
      <div className="mb-5 flex items-center gap-2">
        <Icon name="compass" size={19} />
        <h3 className="text-sm font-semibold">What kind of role are you looking for?</h3>
      </div>
      <label htmlFor="directions" className="mb-2 block text-sm">
        Job directions <span className="ml-1 text-xs text-base-content/50">Optional, up to 3</span>
      </label>
      <input
        id="directions"
        {...field}
        className="input w-full border border-base-300 bg-base-200/25 text-sm"
        placeholder="For example: Frontend development, data analysis"
        maxLength={300}
        aria-invalid={fieldState.invalid}
        aria-describedby="directions-error"
      />
      <p id="directions-error" role="alert" className="text-xs text-error-content">
        {fieldState.error?.message}
      </p>
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
                    ).join(', '),
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
