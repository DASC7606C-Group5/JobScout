import { useController } from 'react-hook-form'

import type { ProfileFormValues } from '../../lib/profile-form'
export function PreferenceFields() {
  const { field: location } = useController<ProfileFormValues, 'preferences.location'>({
    name: 'preferences.location',
  })
  const { field: unrestricted } = useController<
    ProfileFormValues,
    'preferences.location_unrestricted'
  >({ name: 'preferences.location_unrestricted' })
  const { field: employment } = useController<ProfileFormValues, 'preferences.employment_type'>({
    name: 'preferences.employment_type',
  })
  const { field: employmentUnrestricted } = useController<
    ProfileFormValues,
    'preferences.employment_type_unrestricted'
  >({
    name: 'preferences.employment_type_unrestricted',
  })
  const { field: salary } = useController<ProfileFormValues, 'preferences.salary_range'>({
    name: 'preferences.salary_range',
  })
  const { field: workMode } = useController<ProfileFormValues, 'preferences.work_mode'>({
    name: 'preferences.work_mode',
  })
  return (
    <div className="grid gap-5 sm:grid-cols-2">
      <div>
        <label htmlFor="location" className="mb-2 block text-sm">
          Work location
        </label>
        <input
          id="location"
          {...location}
          value={location.value ?? ''}
          className="input w-full rounded-xl border border-base-300 bg-base-200/25 text-sm"
          placeholder="For example: Hong Kong, Shenzhen"
          maxLength={100}
          disabled={unrestricted.value}
        />
        <label className="mt-2.5 flex w-fit cursor-pointer items-center gap-2 text-xs text-base-content/65">
          <input
            type="checkbox"
            className="checkbox checkbox-xs"
            {...unrestricted}
            value="unrestricted"
            checked={unrestricted.value}
          />
          I’m open to any location
        </label>
      </div>
      <div>
        <label htmlFor="employment" className="mb-2 block text-sm">
          Employment type
        </label>
        <select
          id="employment"
          {...employment}
          value={employment.value ?? ''}
          disabled={employmentUnrestricted.value}
          className="select w-full rounded-xl border border-base-300 bg-base-100 text-sm"
        >
          <option value="">Not sure yet — I’ll decide later</option>
          <option value="full-time">Full-time</option>
          <option value="internship">Internship</option>
          <option value="part-time">Part-time</option>
          {employment.value &&
            !['full-time', 'internship', 'part-time'].includes(employment.value) && (
              <option value={employment.value}>{employment.value}</option>
            )}
        </select>
        <label className="mt-2.5 flex w-fit cursor-pointer items-center gap-2 text-xs text-base-content/65">
          <input
            type="checkbox"
            className="checkbox checkbox-xs"
            {...employmentUnrestricted}
            value="unrestricted"
            checked={employmentUnrestricted.value}
          />
          I’m open to any employment type
        </label>
      </div>
      <div>
        <label htmlFor="salary" className="mb-2 block text-sm">
          Expected salary <span className="text-xs text-base-content/50">Optional</span>
        </label>
        <input
          id="salary"
          {...salary}
          value={salary.value ?? ''}
          className="input w-full rounded-xl border border-base-300 bg-base-200/25 text-sm"
          placeholder="For example: HK$20,000–28,000 per month"
          maxLength={100}
        />
      </div>
      <div>
        <label htmlFor="work-mode" className="mb-2 block text-sm">
          Work arrangement <span className="text-xs text-base-content/50">Optional</span>
        </label>
        <select
          id="work-mode"
          {...workMode}
          value={workMode.value ?? ''}
          className="select w-full rounded-xl border border-base-300 bg-base-100 text-sm"
        >
          <option value="">No preference</option>
          <option value="onsite">On-site</option>
          <option value="hybrid">Hybrid</option>
          <option value="remote">Remote</option>
          {workMode.value && !['onsite', 'hybrid', 'remote'].includes(workMode.value) && (
            <option value={workMode.value}>{workMode.value}</option>
          )}
        </select>
      </div>
    </div>
  )
}
