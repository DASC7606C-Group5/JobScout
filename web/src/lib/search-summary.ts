import type { ResumeSessionRequest, UserProfile } from './contracts'
import { parseDirections } from './profile-form'

export const summaryFields = [
  ['education', 'Education', 'array'],
  ['skills', 'Skills', 'array'],
  ['internships', 'Internships', 'array'],
  ['projects', 'Projects', 'array'],
  ['target_directions', 'Job directions', 'array'],
  ['preferences.location', 'Work location', 'text'],
  ['preferences.location_unrestricted', 'Any location', 'boolean'],
  ['preferences.employment_type', 'Employment type', 'text'],
  ['preferences.employment_type_unrestricted', 'Any employment type', 'boolean'],
  ['preferences.salary_range', 'Expected salary', 'text'],
  ['preferences.work_mode', 'Work arrangement', 'text'],
  ['preferences.industry', 'Industry', 'text'],
  ['search_options.result_count', 'Matching jobs to find', 'number'],
] as const
export type SummaryKey = (typeof summaryFields)[number][0]
export type SummaryDraft = Record<SummaryKey, string | boolean | number>

export function summaryDraft(profile: UserProfile): SummaryDraft {
  return Object.fromEntries(
    summaryFields.map(([key, , kind]) => {
      const value =
        key === 'search_options.result_count'
          ? profile.search_options.result_count
          : key.startsWith('preferences.')
            ? profile.preferences[
                key.slice('preferences.'.length) as keyof UserProfile['preferences']
              ]
            : profile[
                key as 'education' | 'skills' | 'internships' | 'projects' | 'target_directions'
              ]
      return [key, kind === 'array' && Array.isArray(value) ? value.join('\n') : (value ?? '')]
    }),
  ) as SummaryDraft
}

export function summaryUpdates(original: SummaryDraft, draft: SummaryDraft, editable: string[]) {
  const updates: ResumeSessionRequest['profile_updates'] = {}
  const editableKeys = new Set(editable)
  for (const [key, , kind] of summaryFields) {
    if (kind === 'number') continue
    if (!editableKeys.has(key) || original[key] === draft[key]) continue
    const value = draft[key]
    updates[key] =
      kind === 'array' && typeof value === 'string'
        ? parseDirections(value)
        : typeof value === 'string'
          ? value.trim() || null
          : Boolean(value)
  }
  if (updates['preferences.location_unrestricted'] === true) updates['preferences.location'] = null
  if (updates['preferences.employment_type_unrestricted'] === true)
    updates['preferences.employment_type'] = null
  return updates
}
