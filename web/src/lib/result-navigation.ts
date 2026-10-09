import type { RecommendationItem } from './contracts'

export interface ResultSearch {
  visibility?: 'hidden' | undefined
  job?: string | undefined
  direction?: string | undefined
  freshness?: 'active' | 'unknown' | 'expired' | undefined
  fit?: RecommendationItem['recommendation_fit'] | undefined
  employment?: string | undefined
  sort?: 'match' | 'newest' | 'oldest' | 'company' | undefined
}

export const sortLabels = {
  recommended: 'Recommended',
  match: 'Highest score',
  newest: 'Newest posted',
  oldest: 'Oldest posted',
  company: 'Company A–Z',
} as const

export const freshnessLabels = {
  active: 'Still hiring',
  unknown: 'Hiring status unknown',
  expired: 'Applications closed',
} as const

function searchText(value: unknown) {
  return typeof value === 'string' && value.length <= 200 && value.trim() ? value : undefined
}

export function resultSearch(value: Record<string, unknown>): ResultSearch {
  return {
    visibility: value.visibility === 'hidden' ? 'hidden' : undefined,
    job: searchText(value.job),
    direction: searchText(value.direction),
    freshness:
      typeof value.freshness === 'string' &&
      ['active', 'unknown', 'expired'].includes(value.freshness)
        ? (value.freshness as ResultSearch['freshness'])
        : undefined,
    fit:
      typeof value.fit === 'string' &&
      ['recommended', 'possible', 'unlikely', 'unknown'].includes(value.fit)
        ? (value.fit as ResultSearch['fit'])
        : undefined,
    employment: searchText(value.employment),
    sort:
      typeof value.sort === 'string' &&
      ['match', 'newest', 'oldest', 'company'].includes(value.sort)
        ? (value.sort as ResultSearch['sort'])
        : undefined,
  }
}

export function visibleJobs(items: RecommendationItem[], search: ResultSearch) {
  const filtered = items.filter(
    ({ job, recommendation_fit }) =>
      (!search.direction ||
        job.target_directions.includes(search.direction) ||
        job.target_direction === search.direction) &&
      (!search.freshness || job.freshness_status === search.freshness) &&
      (!search.fit || recommendation_fit === search.fit) &&
      (!search.employment || job.employment_type === search.employment),
  )
  switch (search.sort) {
    case 'match':
      return filtered.sort((left, right) =>
        compareNumbers(left.match_score?.total ?? null, right.match_score?.total ?? null, true),
      )
    case 'newest':
    case 'oldest':
      return filtered.sort((left, right) =>
        compareNumbers(
          postedDate(left.job.posted_at),
          postedDate(right.job.posted_at),
          search.sort === 'newest',
        ),
      )
    case 'company':
      return filtered.sort((left, right) =>
        left.job.company.localeCompare(right.job.company, 'en', {
          sensitivity: 'base',
          numeric: true,
        }),
      )
    default:
      return filtered
  }
}

export function orderResults(items: RecommendationItem[], resultOrder: string[]) {
  const order = new Map(resultOrder.map((id, index) => [id, index]))
  return [...items].sort((left, right) => {
    const leftOrder = order.get(left.job.job_id)
    const rightOrder = order.get(right.job.job_id)
    if (leftOrder !== undefined || rightOrder !== undefined)
      return (leftOrder ?? Number.MAX_SAFE_INTEGER) - (rightOrder ?? Number.MAX_SAFE_INTEGER)
    return Number(left.review_status !== 'reviewed') - Number(right.review_status !== 'reviewed')
  })
}

function postedDate(value: string | null) {
  const date = value ? Date.parse(value) : NaN
  return Number.isFinite(date) ? date : null
}

function compareNumbers(left: number | null, right: number | null, descending: boolean) {
  if (left === null) return right === null ? 0 : 1
  if (right === null) return -1
  return descending ? right - left : left - right
}

export function nextJobAfterRemoval(items: RecommendationItem[], removed: string) {
  const index = items.findIndex(({ job }) => job.job_id === removed)
  return items[index + 1]?.job.job_id ?? items[index - 1]?.job.job_id
}

export function selectionAfterFilter(
  items: RecommendationItem[],
  current: string | undefined,
  filtered: RecommendationItem[],
) {
  if (!current) return filtered[0]?.job.job_id
  const visible = new Set(filtered.map(({ job }) => job.job_id))
  if (visible.has(current)) return current
  const index = items.findIndex(({ job }) => job.job_id === current)
  return (
    items.slice(index + 1).find(({ job }) => visible.has(job.job_id))?.job.job_id ??
    items
      .slice(0, index)
      .reverse()
      .find(({ job }) => visible.has(job.job_id))?.job.job_id ??
    filtered[0]?.job.job_id
  )
}
