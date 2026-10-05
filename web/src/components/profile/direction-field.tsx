import { useController } from 'react-hook-form'

import { parseDirections, type ProfileFormValues } from '../../lib/profile-form'
import { Icon } from '../icon'

export function DirectionField() {
  const { field } = useController<ProfileFormValues, 'directions'>({
    name: 'directions',
  })
  const selected = parseDirections(field.value)
  return (
    <div className="border-t border-base-300 pt-6">
      <div className="mb-5 flex items-center gap-2">
        <Icon name="compass" size={19} />
        <h3 className="text-sm font-semibold">What kind of role are you looking for?</h3>
      </div>
      <label htmlFor="directions" className="mb-2 block text-sm">
        Job directions <span className="ml-1 text-xs text-base-content/50">Optional</span>
      </label>
      <textarea
        id="directions"
        {...field}
        className="textarea field-sizing-content max-h-96 min-h-24 w-full resize-none border border-base-300 bg-base-200/25 text-sm leading-6"
        rows={3}
        placeholder={'Frontend development\nData analysis'}
        maxLength={300}
        aria-describedby="directions-hint"
      />
      <p id="directions-hint" className="mt-1 text-xs text-base-content/60">
        Enter one direction per line. Keep punctuation within a direction.
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
