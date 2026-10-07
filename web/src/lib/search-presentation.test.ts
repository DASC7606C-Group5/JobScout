import { expect, test } from 'bun:test'

import { createRecommendationFixture, createSessionFixture } from '../../tests/fixtures'
import { searchPresentation } from './search-presentation'

test('a full list of promising reviewed jobs enters comparison while more candidates are reviewed', () => {
  const session = createSessionFixture({
    outcome: 'running',
    run_id: 'run-1',
    current_stage: 'search',
  })
  session.progress.matched_count = 10
  session.progress.discovered_count = 30
  session.progress.analyzed_count = 23
  session.recommendation = {
    session_id: session.session_id,
    generated_at: '2026-10-08T00:00:00Z',
    jobs: Array.from({ length: 10 }, (_, index) => {
      const item = createRecommendationFixture()
      item.job.job_id = `job-${index}`
      item.analysis_status = index === 0 ? 'partial' : 'complete'
      item.recommendation_fit = index === 0 ? 'possible' : 'recommended'
      return item
    }),
    pending_jobs: [],
    notices: [],
    introduction: '',
  }
  expect(searchPresentation(session)).toMatchObject({
    comparing: true,
    canFinish: true,
    finishing: false,
  })
  session.progress.analyzed_count = 26
  expect(searchPresentation(session)).toMatchObject({
    comparing: true,
  })
  session.recommendation.jobs[0]!.analysis_status = 'unavailable'
  expect(searchPresentation(session).comparing).toBe(false)
  session.recommendation.jobs[0]!.analysis_status = 'complete'
  session.recommendation.jobs[0]!.recommendation_fit = 'unlikely'
  expect(searchPresentation(session).comparing).toBe(false)
  session.recommendation.jobs[0]!.recommendation_fit = 'unknown'
  expect(searchPresentation(session).comparing).toBe(false)
  session.recommendation = null
  expect(searchPresentation(session).comparing).toBe(false)
})

test('pending jobs do not trigger comparison and stopping drains reviews before completion', () => {
  const session = createSessionFixture({ outcome: 'running', run_id: 'run-1' })
  session.progress.pending_count = 14
  expect(searchPresentation(session)).toMatchObject({ comparing: false })
  session.progress.retrieval_stopped = true
  expect(searchPresentation(session)).toMatchObject({ finishing: true, canFinish: false })
  session.outcome = 'completed'
  expect(searchPresentation(session)).toMatchObject({
    phase: 'complete',
    finishing: false,
    canFinish: false,
  })
})

test('completed searches can deliver useful results below the display ceiling', () => {
  const session = createSessionFixture({ outcome: 'completed' })
  session.progress.matched_count = 3
  expect(searchPresentation(session)).toMatchObject({
    phase: 'complete',
    comparing: false,
    canFinish: false,
  })
})

test('a failed search cannot remain in the finishing state or offer another stop', () => {
  const session = createSessionFixture({ outcome: 'failed', run_id: 'failed-run' })
  session.progress.retrieval_stopped = true
  expect(searchPresentation(session)).toMatchObject({
    interrupted: true,
    finishing: false,
    canFinish: false,
  })
})
