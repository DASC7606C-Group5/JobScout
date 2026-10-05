import { useController } from 'react-hook-form'

import { resultCountError, type ProfileFormValues } from '../../lib/profile-form'
import { ResultCountField } from './result-count-field'
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
  const { field: resultCount } = useController<ProfileFormValues, 'search_options.result_count'>({
    name: 'search_options.result_count',
    rules: { validate: (value) => resultCountError(value) ?? true },
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
          className="input w-full border border-base-300 bg-base-200/25 text-sm"
          placeholder="For example: Hong Kong, Shenzhen"
          maxLength={1000}
          aria-describedby="location-hint"
          disabled={unrestricted.value}
        />
        <p id="location-hint" className="mt-2 text-xs text-base-content/55">
          Include several places or exclusions, such as “Shanghai except Pudong”.
        </p>
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
        <input
          id="employment"
          {...employment}
          value={employment.value ?? ''}
          disabled={employmentUnrestricted.value}
          className="input w-full border border-base-300 bg-base-200/25 text-sm"
          maxLength={1000}
          placeholder="Full-time or internship, excluding contract"
          aria-describedby="employment-hint"
        />
        <p id="employment-hint" className="mt-2 text-xs text-base-content/55">
          Choose full-time, internship, part-time, contract, or freelance work.
        </p>
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
          className="input w-full border border-base-300 bg-base-200/25 text-sm"
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
          className="select w-full border border-base-300 bg-base-100 text-sm"
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
      <div className="sm:col-span-2">
        <ResultCountField
          id="result-count"
          value={resultCount.value}
          onChange={resultCount.onChange}
          inputRef={resultCount.ref}
        />
      </div>
    </div>
  )
}
