import { is } from 'valibot'

import type { MatchScore } from '../api/types.gen'
import { vMatchScore } from './api-schemas'
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

export function isMatchScore(value: unknown): value is MatchScore {
  return is(vMatchScore, value)
}
