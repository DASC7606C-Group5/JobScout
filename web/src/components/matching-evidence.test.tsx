import { expect, test } from 'bun:test'

import { renderToStaticMarkup } from 'react-dom/server'

import { createRecommendationFixture } from '../../tests/fixtures'
import { MatchingEvidence } from './matching-evidence'

test('matching evidence preserves excerpts and source links without exposing document IDs', () => {
  const reason = createRecommendationFixture().matching_reasons[0]!
  reason.profile_evidence = [
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
  const html = renderToStaticMarkup(<MatchingEvidence reasons={[reason]} />)
  for (const reference of [...reason.job_evidence, ...reason.profile_evidence]) {
    expect(html).toContain(reference.excerpt)
    expect(html).not.toContain(reference.document_id)
  }
  expect(html).toContain(`href="${reason.job_evidence[0]!.source_url}"`)
  expect(html).toContain('rel="noopener noreferrer"')
})

test('unsupported source URLs are omitted without removing the evidence quote', () => {
  const reason = createRecommendationFixture().matching_reasons[0]!
  reason.job_evidence[0]!.source_url = 'javascript:alert(1)'
  const html = renderToStaticMarkup(<MatchingEvidence reasons={[reason]} />)
  expect(html).toContain(reason.job_evidence[0]!.excerpt)
  expect(html).not.toContain('href=')
  expect(html).not.toContain('javascript:')
})
