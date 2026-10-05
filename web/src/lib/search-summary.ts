import type { ResumeSessionRequest, UserProfile } from './contracts'
import { parseDirections } from './profile-form'

export const summaryFields = [
  ['education', '教育背景', 'array'],
  ['skills', '技能', 'array'],
  ['internships', '实习经历', 'array'],
  ['projects', '项目经历', 'array'],
  ['target_directions', '求职方向（最多三个）', 'array'],
  ['preferences.location', '工作地点', 'text'],
  ['preferences.location_unrestricted', '不限地点', 'boolean'],
  ['preferences.employment_type', '工作类型', 'text'],
  ['preferences.employment_type_unrestricted', '不限工作类型', 'boolean'],
  ['preferences.salary_range', '期望薪资', 'text'],
  ['preferences.work_mode', '工作方式', 'text'],
  ['preferences.industry', '行业', 'text'],
] as const
export type SummaryKey = (typeof summaryFields)[number][0]
export type SummaryDraft = Record<SummaryKey, string | boolean>

export function summaryDirectionError(draft: SummaryDraft): string | null {
  return parseDirections(String(draft.target_directions)).length > 3
    ? '最多选择三个求职方向，请减少方向后再保存。'
    : null
}

export function summaryDraft(profile: UserProfile): SummaryDraft {
  return Object.fromEntries(
    summaryFields.map(([key, , kind]) => {
      const value = key.startsWith('preferences.')
        ? profile.preferences[key.slice('preferences.'.length) as keyof UserProfile['preferences']]
        : profile[key as 'education' | 'skills' | 'internships' | 'projects' | 'target_directions']
      return [key, kind === 'array' && Array.isArray(value) ? value.join('\n') : (value ?? '')]
    }),
  ) as SummaryDraft
}

export function summaryUpdates(original: SummaryDraft, draft: SummaryDraft, editable: string[]) {
  const updates: ResumeSessionRequest['profile_updates'] = {}
  const editableKeys = new Set(editable)
  for (const [key, , kind] of summaryFields) {
    if (!editableKeys.has(key) || original[key] === draft[key]) continue
    const value = draft[key]
    updates[key] =
      kind === 'array' && typeof value === 'string'
        ? [
            ...new Set(
              value
                .split(/[\n,，、]/)
                .map((part) => part.trim())
                .filter(Boolean),
            ),
          ]
        : typeof value === 'string'
          ? value.trim() || null
          : value
  }
  if (updates['preferences.location_unrestricted'] === true) updates['preferences.location'] = null
  if (updates['preferences.employment_type_unrestricted'] === true)
    updates['preferences.employment_type'] = null
  return updates
}
