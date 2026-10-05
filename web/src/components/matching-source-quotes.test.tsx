import { expect, test } from 'bun:test'

import { renderToStaticMarkup } from 'react-dom/server'

import { createRecommendationFixture } from '../../tests/fixtures'
import { MatchingSourceQuotes } from './matching-source-quotes'

test('matching source quotes preserve excerpts and source links without exposing document IDs', () => {
  const reason = createRecommendationFixture().matching_reasons[0]!
  reason.profile_source_quotes = [
    {
      document_id: 'profile:session-secret:resume',
      excerpt: 'Resume project experience',
      source_url: null,
    },
    {
      document_id: 'profile:session-secret:description',
      excerpt: 'Experience from introduction',
      source_url: null,
    },
    {
      document_id: 'profile:session-secret:answer:request-secret',
      excerpt: 'Additional experience',
      source_url: null,
    },
  ]
  const html = renderToStaticMarkup(<MatchingSourceQuotes reasons={[reason]} />)
  for (const reference of [...reason.job_source_quotes, ...reason.profile_source_quotes]) {
    expect(html).toContain(reference.excerpt)
    expect(html).not.toContain(reference.document_id)
  }
  expect(html).toContain(`href="${reason.job_source_quotes[0]!.source_url}"`)
  expect(html).toContain('rel="noopener noreferrer"')
})

test('unsupported source URLs are omitted without removing the source quote', () => {
  const reason = createRecommendationFixture().matching_reasons[0]!
  reason.job_source_quotes[0]!.source_url = 'javascript:alert(1)'
  const html = renderToStaticMarkup(<MatchingSourceQuotes reasons={[reason]} />)
  expect(html).toContain(reason.job_source_quotes[0]!.excerpt)
  expect(html).not.toContain('href=')
  expect(html).not.toContain('javascript:')
})
