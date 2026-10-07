import { expect, test } from 'bun:test'

import { createRecommendationFixture } from '../../tests/fixtures'
import { recommendationStatus, type ReviewIssue } from './job-status'
import { isRecommendationItem } from './session-response'

test.each([
  ['timeout', 'timeout'],
  ['service_unavailable', 'unavailable'],
  ['invalid_output', 'invalid'],
  ['unverifiable_claims', 'invalid'],
  ['insufficient_job_information', 'insufficient'],
  ['failed', 'failed'],
] as const)('an unavailable assessment preserves the %s classification', (code, expected) => {
  const item = createRecommendationFixture()
  item.analysis_status = 'unavailable'
  item.review_issue = { code, stage: 'matching' }
  expect(recommendationStatus(item, false)).toBe(expected)
})

test('partial results survive diagnostics and uncertain conditions', () => {
  const item = createRecommendationFixture()
  item.analysis_status = 'partial'
  item.verification_status = 'pending'
  item.unknown_conditions = ['location']
  item.review_issue = { code: 'unverifiable_claims', stage: 'matching' }
  expect(recommendationStatus(item, false)).toBe('partial')
  item.analysis_status = 'complete'
  item.review_issue = null
  expect(recommendationStatus(item, false)).toBe('unverified')
  item.verification_status = 'confirmed'
  expect(recommendationStatus(item, false)).toBe('reviewed')
})

test('retry progress supersedes an old failure and stopped work stays unreviewed', () => {
  const item = createRecommendationFixture()
  item.analysis_status = 'unavailable'
  item.review_issue = { code: 'timeout', stage: 'matching' }
  item.review_status = 'reviewing'
  expect(recommendationStatus(item, true)).toBe('reviewing')
  item.review_status = 'not_reviewed'
  item.review_issue = { code: 'stopped', stage: null }
  expect(recommendationStatus(item, false)).toBe('not_reviewed')
})

test('wire contracts reject unknown diagnostic codes and private stages', () => {
  const item = createRecommendationFixture()
  for (const issue of [
    { code: 'private_provider_message', stage: 'matching' },
    { code: 'timeout', stage: 'private_stage' },
  ]) {
    item.review_issue = issue as ReviewIssue
    expect(isRecommendationItem(item)).toBe(false)
  }
})
