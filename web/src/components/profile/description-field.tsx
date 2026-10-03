import { useController } from 'react-hook-form'

import type { ProfileFormValues } from '../../lib/profile-form'
export function DescriptionField() {
  const { field, fieldState } = useController<ProfileFormValues, 'description'>({
    name: 'description',
    rules: {
      validate: (value, values) =>
        Boolean(value.trim() || values.resume) || '请填写个人介绍，或添加一份简历。',
    },
  })
  return (
    <div>
      <div className="mb-2.5 flex items-center justify-between">
        <label htmlFor="description" className="text-sm font-semibold">
          个人介绍
        </label>
        <span className="text-xs text-base-content/55">与简历至少填写一项</span>
      </div>
      <textarea
        {...field}
        id="description"
        className="textarea min-h-36 w-full resize-y rounded-xl border border-base-300 bg-base-200/25 p-4 text-sm leading-7"
        placeholder="聊聊你的教育背景、擅长的技能、项目或实习经历，以及你对下一份工作的期待……"
        maxLength={10000}
        aria-describedby="description-hint profile-error"
        aria-invalid={fieldState.invalid}
      />
      <div
        id="description-hint"
        className="mt-2 flex justify-between gap-3 text-xs text-base-content/55"
      >
        <span>不必写得完美，稍后还可以补充。</span>
        <span className="shrink-0 tabular-nums">
          {field.value.length.toLocaleString()} / 10,000
        </span>
      </div>
    </div>
  )
}
