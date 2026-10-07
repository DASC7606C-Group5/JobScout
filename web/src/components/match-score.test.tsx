import { expect, test } from 'bun:test'

import { renderToStaticMarkup } from 'react-dom/server'

import { dimensionLabels, isMatchScore, type MatchScore } from '../lib/matching-contracts'
import { MatchScoreBadge, MatchScoreDetail } from './match-score'

function partialScore(): MatchScore {
  return {
    total: 80,
    assessed_weight: 30,
    applicable_weight: 95,
    coverage: 32,
    provisional: true,
    completeness: 'partial',
    input_fingerprint: 'input',
    dimensions: Object.keys(dimensionLabels).map((id, index) => ({
      id: id as keyof typeof dimensionLabels,
      score: index === 0 ? 80 : null,
      status: index === 0 ? 'assessed' : index === 4 ? 'not_applicable' : 'unknown',
      weight: [30, 25, 20, 10, 5, 10][index]!,
      explanation: index === 0 ? 'Built the requested interface' : '',
      requirement_ids: [],
      profile_fact_ids: [],
      job_source_quotes:
        index === 0 ? [{ document_id: 'jd', excerpt: 'Build interfaces', source_url: null }] : [],
      profile_source_quotes:
        index === 0
          ? [{ document_id: 'resume', excerpt: 'Built a React interface', source_url: null }]
          : [],
      missing_information: index === 1 ? ['Daily duties not provided'] : [],
      input_fingerprint: id,
    })),
  }
}

test('partial scores retain unknown areas and supplied source excerpts', () => {
  const html = renderToStaticMarkup(<MatchScoreDetail score={partialScore()} />)
  expect(html).toContain('Match 80/100')
  expect(html).toContain('Unknown')
  expect(html).toContain('Not applicable')
  expect(html).toContain('Build interfaces')
  expect(html).toContain('Built a React interface')
  expect(html).toContain('Daily duties not provided')
  // Only the assessed axis produces a data point; unknown neighbors make no connecting lines.
  expect(html.match(/<circle /g)).toHaveLength(1)
  expect(html).not.toContain('stroke-width="2"')
})

test('all unknown has no invented total or radar data points', () => {
  const score = partialScore()
  score.total = null
  score.dimensions = score.dimensions.map((dimension) => ({
    ...dimension,
    score: null,
    status: 'unknown',
  }))
  const html = renderToStaticMarkup(<MatchScoreDetail score={score} />)
  expect(html).toContain('Match unknown')
  expect(html).not.toContain('<circle ')
  expect(renderToStaticMarkup(<MatchScoreBadge score={null} />)).toBe('')
})

test('wire contract rejects missing axes and numeric unknowns before display', () => {
  const score = partialScore()
  expect(isMatchScore(score)).toBe(true)
  expect(isMatchScore({ ...score, dimensions: score.dimensions.slice(1) })).toBe(false)
  score.dimensions[1]!.score = 0
  expect(isMatchScore(score)).toBe(false)
})
