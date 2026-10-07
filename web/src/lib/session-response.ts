import { is } from 'valibot'

import { vRecommendationItem, vSessionResponse } from './api-schemas'
import type { RecommendationItem, ScoutSession } from './contracts'

export function isRecommendationItem(value: unknown): value is RecommendationItem {
  return is(vRecommendationItem, value)
}

export function isSessionResponse(value: unknown): value is ScoutSession {
  return is(vSessionResponse, value)
}
