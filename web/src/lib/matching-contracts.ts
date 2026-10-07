import type { SourceQuoteReference } from './contracts'

export const dimensionLabels = {
  skills: 'Skills',
  responsibilities: 'Responsibilities',
  experience: 'Experience',
  seniority: 'Seniority',
  education: 'Education',
  preferences: 'Preferences',
} as const

export type DimensionId = keyof typeof dimensionLabels

export interface MatchDimension {
  id: DimensionId
  score: number | null
  status: 'assessed' | 'unknown' | 'not_applicable'
  weight: number
  explanation: string
  requirement_ids: string[]
  profile_fact_ids: string[]
  job_source_quotes: SourceQuoteReference[]
  profile_source_quotes: SourceQuoteReference[]
  missing_information: string[]
  input_fingerprint: string
}

export interface MatchScore {
  total: number | null
  dimensions: MatchDimension[]
  assessed_weight: number
  applicable_weight: number
  coverage: number
  provisional: boolean
  completeness: 'complete' | 'partial' | 'unknown'
  input_fingerprint: string
}

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}
function percentage(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0 && value <= 100
}
function strings(value: unknown) {
  return Array.isArray(value) && value.every((entry) => typeof entry === 'string')
}
function quotes(value: unknown) {
  return (
    Array.isArray(value) &&
    value.every(
      (quote) =>
        record(quote) &&
        typeof quote.document_id === 'string' &&
        typeof quote.excerpt === 'string' &&
        (quote.source_url === null || typeof quote.source_url === 'string'),
    )
  )
}

export function isMatchScore(value: unknown): value is MatchScore {
  if (!record(value)) return false
  const ids = Object.keys(dimensionLabels)
  return (
    (value.total === null || percentage(value.total)) &&
    percentage(value.coverage) &&
    percentage(value.assessed_weight) &&
    percentage(value.applicable_weight) &&
    typeof value.provisional === 'boolean' &&
    typeof value.input_fingerprint === 'string' &&
    ['complete', 'partial', 'unknown'].includes(String(value.completeness)) &&
    Array.isArray(value.dimensions) &&
    value.dimensions.length === 6 &&
    value.dimensions.every(
      (dimension, index) =>
        record(dimension) &&
        dimension.id === ids[index] &&
        percentage(dimension.weight) &&
        (dimension.status === 'assessed'
          ? percentage(dimension.score)
          : ['unknown', 'not_applicable'].includes(String(dimension.status)) &&
            dimension.score === null) &&
        typeof dimension.explanation === 'string' &&
        typeof dimension.input_fingerprint === 'string' &&
        strings(dimension.requirement_ids) &&
        strings(dimension.profile_fact_ids) &&
        strings(dimension.missing_information) &&
        quotes(dimension.job_source_quotes) &&
        quotes(dimension.profile_source_quotes),
    )
  )
}
