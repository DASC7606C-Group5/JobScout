import type { RecommendationItem } from './contracts'

export interface ResultSearch {
  job?: string | undefined
  direction?: string | undefined
  freshness?: 'active' | 'unknown' | 'expired' | undefined
}

export function resultSearch(value: Record<string, unknown>): ResultSearch {
  return {
    job:
      typeof value.job === 'string' && value.job.length <= 200 && value.job.trim()
        ? value.job
        : undefined,
    direction:
      typeof value.direction === 'string' && value.direction.length <= 200 && value.direction.trim()
        ? value.direction
        : undefined,
    freshness:
      typeof value.freshness === 'string' &&
      ['active', 'unknown', 'expired'].includes(value.freshness)
        ? (value.freshness as ResultSearch['freshness'])
        : undefined,
  }
}

export function visibleJobs(items: RecommendationItem[], search: ResultSearch) {
  return items.filter(
    ({ job }) =>
      (!search.direction ||
        job.target_directions.includes(search.direction) ||
        job.target_direction === search.direction) &&
      (!search.freshness || job.freshness_status === search.freshness),
  )
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
