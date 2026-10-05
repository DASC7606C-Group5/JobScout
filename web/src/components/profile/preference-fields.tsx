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
          工作地点
        </label>
        <input
          id="location"
          {...location}
          value={location.value ?? ''}
          className="input w-full rounded-xl border border-base-300 bg-base-200/25 text-sm"
          placeholder="例如：香港、深圳"
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
          我接受不限地点
        </label>
      </div>
      <div>
        <label htmlFor="employment" className="mb-2 block text-sm">
          工作类型
        </label>
        <select
          id="employment"
          {...employment}
          value={employment.value ?? ''}
          disabled={employmentUnrestricted.value}
          className="select w-full rounded-xl border border-base-300 bg-base-100 text-sm"
        >
          <option value="">还没想好，稍后确认</option>
          <option value="full-time">全职</option>
          <option value="internship">实习</option>
          <option value="part-time">兼职</option>
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
          我接受不限工作类型
        </label>
      </div>
      <div>
        <label htmlFor="salary" className="mb-2 block text-sm">
          期望薪资 <span className="text-xs text-base-content/50">选填</span>
        </label>
        <input
          id="salary"
          {...salary}
          value={salary.value ?? ''}
          className="input w-full rounded-xl border border-base-300 bg-base-200/25 text-sm"
          placeholder="例如：HK$ 20,000–28,000 / 月"
          maxLength={100}
        />
      </div>
      <div>
        <label htmlFor="work-mode" className="mb-2 block text-sm">
          工作方式 <span className="text-xs text-base-content/50">选填</span>
        </label>
        <select
          id="work-mode"
          {...workMode}
          value={workMode.value ?? ''}
          className="select w-full rounded-xl border border-base-300 bg-base-100 text-sm"
        >
          <option value="">不限</option>
          <option value="onsite">办公室</option>
          <option value="hybrid">混合办公</option>
          <option value="remote">远程</option>
          {workMode.value && !['onsite', 'hybrid', 'remote'].includes(workMode.value) && (
            <option value={workMode.value}>{workMode.value}</option>
          )}
        </select>
      </div>
    </div>
  )
}
