import { expect, test } from 'bun:test'

import type { SourceOutcome } from './contracts'
import { sourceOutcomeRows } from './source-outcomes'

const outcome: SourceOutcome = {
  request_index: 0,
  target_direction: 'Data Analyst',
  source: 'synthetic-replay',
  candidate_count: 4,
  returned_count: 4,
  incomplete_count: 0,
  excerpt_count: 0,
  elapsed_seconds: 0,
  status: 'ok',
}

test('identical source outcomes from multiple rounds have one stable row and a repeat count', () => {
  const rows = sourceOutcomeRows([
    outcome,
    { ...outcome },
    { ...outcome, status: 'empty', returned_count: 0 },
  ])
  expect(rows.map(({ count }) => count)).toEqual([2, 1])
  expect(new Set(rows.map(({ key }) => key)).size).toBe(2)
  expect(rows[0]?.outcome).toEqual(outcome)
  expect(sourceOutcomeRows([])).toEqual([])
})
