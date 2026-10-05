import type { ScoutInput } from './contracts'

export type ProfileFormValues = Omit<ScoutInput, 'target_directions'> & { directions: string }

export function createProfileDraft(): ProfileFormValues {
  return {
    description: '',
    resume: null,
    directions: '',
    preferences: {
      location: '',
      location_unrestricted: false,
      employment_type: null,
      employment_type_unrestricted: false,
      salary_range: null,
      work_mode: null,
      industry: null,
    },
  }
}

export function parseDirections(value: string): string[] {
  return [
    ...new Set(
      value
        .split(/[,，、]/)
        .map((part) => part.trim())
        .filter(Boolean),
    ),
  ]
}

export function toScoutInput({ directions, ...values }: ProfileFormValues): ScoutInput {
  const { preferences } = values
  return {
    ...values,
    description: values.description.trim(),
    target_directions: parseDirections(directions),
    preferences: {
      ...preferences,
      location: preferences.location_unrestricted ? null : preferences.location?.trim() || null,
      employment_type: preferences.employment_type_unrestricted
        ? null
        : preferences.employment_type || null,
      salary_range: preferences.salary_range?.trim() || null,
      work_mode: preferences.work_mode || null,
    },
  }
}
