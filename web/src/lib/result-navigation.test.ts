import { expect, test } from 'bun:test'

import { createRecommendationFixture } from '../../tests/fixtures'
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
      private: 'value',
    }),
  ).toEqual({ job: undefined, direction: undefined, freshness: undefined })
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
