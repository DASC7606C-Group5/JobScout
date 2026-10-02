import { useController } from 'react-hook-form'

import { parseDirections, type ProfileFormValues } from '../../lib/profile-form'
import { Icon } from '../icon'

export function DirectionField() {
  const { field } = useController<ProfileFormValues, 'directions'>({ name: 'directions' })
  const selected = parseDirections(field.value)
  return (
    <div className="border-t border-base-300 pt-6">
      <div className="mb-5 flex items-center gap-2">
        <Icon name="compass" size={19} />
        <h3 className="text-sm font-semibold">你想往哪个方向走？</h3>
      </div>
      <label htmlFor="directions" className="mb-2 block text-sm">
        求职方向 <span className="ml-1 text-xs text-base-content/50">可填写多个</span>
      </label>
      <input
        id="directions"
        {...field}
        className="input w-full rounded-xl border border-base-300 bg-base-200/25 text-sm"
        placeholder="例如：前端开发，数据分析"
        maxLength={300}
      />
      <div className="mt-2.5 flex flex-wrap gap-2">
        {['前端开发', '数据分析', '产品设计', '软件工程'].map((direction) => {
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
                  ).join('，'),
                )
              }
            >
              {active ? '✓' : '+'} {direction}
            </button>
          )
        })}
      </div>
    </div>
  )
}
