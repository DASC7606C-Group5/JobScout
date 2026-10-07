import { expect, test } from 'bun:test'

import { createMatchScoreFixture, createRecommendationFixture } from '../../tests/fixtures'
import {
  nextJobAfterRemoval,
  resultSearch,
  selectionAfterFilter,
  visibleJobs,
} from './result-navigation'

test('combined result filters preserve ranking and match any merged direction', () => {
  const first = createRecommendationFixture()
  first.job.target_directions = ['Frontend development', 'Data analysis']
  const second = structuredClone(first)
  second.job.job_id = 'second'
  second.job.freshness_status = 'active'
  const third = structuredClone(second)
  third.job.job_id = 'third'
  third.job.target_directions = ['Data analysis']
  expect(
    visibleJobs([first, second, third], { direction: 'Data analysis', freshness: 'active' }).map(
      ({ job }) => job.job_id,
    ),
  ).toEqual(['second', 'third'])
})

test('removing a saved selection chooses its next neighbor or the preceding last item', () => {
  const items = ['first', 'middle', 'last'].map((id) => {
    const item = createRecommendationFixture()
    item.job.job_id = id
    return item
  })
  expect(nextJobAfterRemoval(items, 'middle')).toBe('last')
  expect(nextJobAfterRemoval(items, 'last')).toBe('middle')
  expect(nextJobAfterRemoval([items[0]!], 'first')).toBeUndefined()
})

test('untrusted route parameters cannot introduce invalid filter or object selections', () => {
  expect(
    resultSearch({
      job: { secret: true },
      direction: ['injected'],
      freshness: ['active'],
      employment: ['full-time'],
      fit: 'invented',
      sort: 'invented',
      private: 'value',
    }),
  ).toEqual({
    job: undefined,
    direction: undefined,
    freshness: undefined,
    employment: undefined,
    fit: undefined,
    sort: undefined,
  })
})

test('direction, listing status, match result and employment filters compose', () => {
  const first = createRecommendationFixture()
  first.job.freshness_status = 'active'
  first.job.target_directions.push('Software engineering')
  first.recommendation_fit = 'possible'
  const second = structuredClone(first)
  second.job.job_id = 'part-time'
  second.job.employment_type = 'part-time'
  const third = structuredClone(first)
  third.job.job_id = 'expired'
  third.job.freshness_status = 'expired'
  const fourth = structuredClone(first)
  fourth.job.job_id = 'recommended'
  fourth.recommendation_fit = 'recommended'
  const fifth = structuredClone(first)
  fifth.job.job_id = 'other-direction'
  fifth.job.target_directions = []
  const search = resultSearch({
    direction: 'Software engineering',
    freshness: 'active',
    fit: 'possible',
    employment: 'full-time',
    sort: 'newest',
  })
  expect(
    visibleJobs([first, second, third, fourth, fifth], search).map(({ job }) => job.job_id),
  ).toEqual([first.job.job_id])
})

test('match sorting keeps zero scores ahead of missing scores and preserves ties and input order', () => {
  const items = ['unscored', 'zero', 'high', 'tie', 'unknown-total'].map((id) => {
    const item = createRecommendationFixture()
    item.job.job_id = id
    return item
  })
  for (const [index, total] of [
    [1, 0],
    [2, 90],
    [3, 90],
  ] as const) {
    items[index]!.match_score = { ...createMatchScoreFixture(), total }
  }
  items[4]!.match_score = { ...createMatchScoreFixture(), total: null }
  const original = structuredClone(items)
  expect(visibleJobs(items, { sort: 'match' }).map(({ job }) => job.job_id)).toEqual([
    'high',
    'tie',
    'zero',
    'unscored',
    'unknown-total',
  ])
  expect(items).toEqual(original)
  expect(visibleJobs(items, {}).map(({ job }) => job.job_id)).toEqual([
    'unscored',
    'zero',
    'high',
    'tie',
    'unknown-total',
  ])
})

test('posting date sorts keep missing and invalid dates last without using retrieval dates', () => {
  const items = (
    [
      ['missing', null],
      ['older', '2026-10-01T08:00:00+08:00'],
      ['newer', '2026-10-07T00:00:00Z'],
      ['same-time', '2026-10-07T08:00:00+08:00'],
      ['invalid', 'not-a-date'],
    ] as const
  ).map(([id, posted_at]) => {
    const item = createRecommendationFixture()
    item.job.job_id = id
    item.job.posted_at = posted_at
    item.job.fetched_at = '2026-10-08T00:00:00Z'
    return item
  })
  expect(visibleJobs(items, { sort: 'newest' }).map(({ job }) => job.job_id)).toEqual([
    'newer',
    'same-time',
    'older',
    'missing',
    'invalid',
  ])
  expect(visibleJobs(items, { sort: 'oldest' }).map(({ job }) => job.job_id)).toEqual([
    'older',
    'newer',
    'same-time',
    'missing',
    'invalid',
  ])
})

test('company sorting is case-insensitive, sorts numbers naturally and keeps selected job identity', () => {
  const items = ['Studio 10', 'alpha', 'Alpha', 'Studio 2'].map((company, index) => {
    const item = createRecommendationFixture()
    item.job.job_id = `company-${index}`
    item.job.company = company
    return item
  })
  const sorted = visibleJobs(items, { sort: 'company' })
  expect(sorted.map(({ job }) => job.job_id)).toEqual([
    'company-1',
    'company-2',
    'company-3',
    'company-0',
  ])
  expect(selectionAfterFilter(items, 'company-0', sorted)).toBe('company-0')
  expect(nextJobAfterRemoval(sorted, 'company-3')).toBe('company-0')
})

test('filter changes keep an eligible selection or choose the nearest remaining neighbor', () => {
  const items = ['first', 'middle', 'last'].map((id) => {
    const item = createRecommendationFixture()
    item.job.job_id = id
    return item
  })
  expect(selectionAfterFilter(items, 'middle', [items[0]!, items[1]!])).toBe('middle')
  expect(selectionAfterFilter(items, 'middle', [items[0]!, items[2]!])).toBe('last')
  expect(selectionAfterFilter(items, 'last', [items[0]!, items[1]!])).toBe('middle')
  expect(selectionAfterFilter(items, 'middle', [])).toBeUndefined()
})
