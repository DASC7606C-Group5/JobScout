import { expect, test } from 'bun:test'

import { renderToStaticMarkup } from 'react-dom/server'

import { createRecommendationFixture } from '../../tests/fixtures'
import { MatchingEvidence } from './matching-evidence'

test('matching evidence preserves quotes and source links while presenting readable provenance', () => {
  const reason = createRecommendationFixture().matching_reasons[0]!
  reason.profile_evidence = [
    { document_id: 'profile:session-secret:resume', excerpt: '简历项目经历', source_url: null },
    { document_id: 'profile:session-secret:description', excerpt: '自述经历', source_url: null },
    {
      document_id: 'profile:session-secret:answer:request-secret',
      excerpt: '补充经历',
      source_url: null,
    },
  ]
  const html = renderToStaticMarkup(<MatchingEvidence reasons={[reason]} />)
  for (const label of ['岗位来源', '已上传简历', '自我介绍', '补充回答'])
    expect(html).toContain(label)
  for (const reference of [...reason.job_evidence, ...reason.profile_evidence]) {
    expect(html).toContain(`“${reference.excerpt}”`)
    expect(html).not.toContain(reference.document_id)
  }
  expect(html).toContain('href="https://example.test/jobs/1"')
  expect(html).toContain('rel="noopener noreferrer"')
})

test('unsupported source URLs are omitted without removing the evidence quote', () => {
  const reason = createRecommendationFixture().matching_reasons[0]!
  reason.job_evidence[0]!.source_url = 'javascript:alert(1)'
  const html = renderToStaticMarkup(<MatchingEvidence reasons={[reason]} />)
  expect(html).toContain('React development experience required.')
  expect(html).not.toContain('href=')
  expect(html).not.toContain('javascript:')
})
