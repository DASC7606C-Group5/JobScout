export type { MatchScore, MatchDimension } from '../api/types.gen'

export const dimensionLabels = {
  skills: 'Skills',
  responsibilities: 'Responsibilities',
  experience: 'Experience',
  seniority: 'Seniority',
  education: 'Education',
  preferences: 'Preferences',
} as const

export type DimensionId = keyof typeof dimensionLabels
