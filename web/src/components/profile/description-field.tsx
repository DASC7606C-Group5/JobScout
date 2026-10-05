import { useController } from 'react-hook-form'

import type { ProfileFormValues } from '../../lib/profile-form'
export function DescriptionField() {
  const { field, fieldState } = useController<ProfileFormValues, 'description'>({
    name: 'description',
    rules: {
      validate: (value, values) =>
        Boolean(value.trim() || values.resume) || 'Add an introduction or upload a resume.',
    },
  })
  return (
    <div>
      <div className="mb-2.5 flex items-center justify-between">
        <label htmlFor="description" className="text-sm font-semibold">
          About you
        </label>
        <span className="text-xs text-base-content/55">Provide an introduction or a resume</span>
      </div>
      <textarea
        {...field}
        id="description"
        className="textarea field-sizing-content max-h-96 min-h-36 w-full resize-none rounded-xl border border-base-300 bg-base-200/25 p-4 text-sm leading-7"
        placeholder="Tell us about your education, skills, projects or internships, and what you’re looking for in your next role…"
        maxLength={10000}
        aria-describedby="description-hint profile-error"
        aria-invalid={fieldState.invalid}
      />
      <div
        id="description-hint"
        className="mt-2 flex justify-between gap-3 text-xs text-base-content/55"
      >
        <span>It doesn’t have to be perfect. You can add more later.</span>
        <span className="shrink-0 tabular-nums">
          {field.value.length.toLocaleString()} / 10,000
        </span>
      </div>
    </div>
  )
}
