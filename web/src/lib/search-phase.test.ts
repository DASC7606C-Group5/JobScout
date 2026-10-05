import { expect, test } from 'bun:test'

import { createSessionFixture } from '../../tests/fixtures'
import { searchPhase } from './search-phase'

test('profile processing and answer validation do not imply a job search', () => {
  for (const current_stage of [
    'ingest',
    'profile',
    'extract',
    'validate',
    'clarify',
    'confirm',
    'edit_conditions',
  ]) {
    expect(searchPhase(createSessionFixture({ outcome: 'running', current_stage }))).toBe('profile')
  }
})

test('accepted search prepares before a run is available and reviews continue after retrieval stops', () => {
  const session = createSessionFixture({ outcome: 'running', current_stage: 'search' })
  expect(searchPhase(session)).toBe('preparing')
  session.run_id = 'accepted-run'
  expect(searchPhase(session)).toBe('search')
  session.progress.retrieval_stopped = true
  expect(searchPhase(session)).toBe('review')
})
