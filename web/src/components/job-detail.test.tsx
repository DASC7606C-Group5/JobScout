import { expect, test } from 'bun:test'

import { createRef } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

import { createRecommendationFixture } from '../../tests/fixtures'
import type { ApplicantNotice } from '../lib/contracts'
import { SearchFailure } from './discovery/search-status'
import { JobDetail } from './job-detail'

const noop = () => {}

test('detail retains supplied facts and quotes and excludes notices for discarded jobs', () => {
  const item = createRecommendationFixture()
  item.job.description = 'Original listing content'
  item.matching_reasons[0]!.profile_source_quotes[0]!.excerpt =
    'I worked on Group 6: detail_limit=None'
  const notice: ApplicantNotice = {
    code: 'listing_incomplete',
    scope: 'job',
    job_id: item.job.job_id,
    message: 'public-notice-sentinel',
    action: 'open_listing',
    source: null,
    preference: null,
  }
  item.notices = [notice]
  const html = renderToStaticMarkup(
    <JobDetail
      item={item}
      saved={false}
      onToggle={noop}
      onBack={noop}
      headingRef={createRef()}
      notices={[notice, { ...notice, job_id: 'discarded', message: 'discarded-notice-sentinel' }]}
    />,
  )
  expect(html).toContain(item.job.description)
  expect(html).toContain(item.matching_reasons[0]!.profile_source_quotes[0]!.excerpt)
  expect(html).toContain(item.matching_reasons[1]!.explanation)
  expect(html).not.toContain('discarded-notice-sentinel')
  expect(html.split(notice.message)).toHaveLength(2)
  expect(html).toContain(`href="${item.job.source_url}"`)
})

test('unavailable analysis retains job facts but does not display unsupported match or preparation output', () => {
  const item = createRecommendationFixture()
  item.analysis_status = 'unavailable'
  item.preparation_suggestions = ['unsupported-preparation-sentinel']
  item.matching_reasons[0]!.explanation = 'unsupported-match-sentinel'
  item.matching_reasons[1]!.explanation = 'unsupported-missing-sentinel'
  const html = renderToStaticMarkup(
    <JobDetail
      item={item}
      saved={false}
      onToggle={noop}
      onBack={noop}
      headingRef={createRef()}
      notices={[]}
    />,
  )
  expect(html).toContain(item.job.title)
  expect(html).toContain(item.job.description)
  expect(html).not.toContain('unsupported-preparation-sentinel')
  expect(html).not.toContain('unsupported-match-sentinel')
  expect(html).not.toContain('unsupported-missing-sentinel')
})

test('workflow failure presents safe recovery instead of private error content', () => {
  const diagnostic = 'private-operator-detail'
  const html = renderToStaticMarkup(
    <SearchFailure
      errors={[
        {
          code: 'private-error-code',
          message: diagnostic,
          action: null,
        },
      ]}
      onRetry={noop}
      onEdit={noop}
      retryable={false}
    />,
  )
  for (const value of [diagnostic, 'private-error-code']) expect(html).not.toContain(value)
})
