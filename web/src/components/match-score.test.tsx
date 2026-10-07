import { expect, test } from 'bun:test'

import { renderToStaticMarkup } from 'react-dom/server'

import { createMatchScoreFixture } from '../../tests/fixtures'
import { dimensionLabels, isMatchScore } from '../lib/matching-contracts'
import { MatchRadar, MatchScoreSummary, MatchScoreValue } from './match-score'

test('each dimension retains its score status and explanation for accessible inspection', () => {
  const score = createMatchScoreFixture()
  const html = renderToStaticMarkup(<MatchRadar score={score} />)
  for (const dimension of score.dimensions) {
    const value =
      dimension.score !== null
        ? `${dimension.score}/100`
        : dimension.status === 'not_applicable'
          ? 'Not applicable'
          : 'Not enough information'
    expect(html).toContain(`aria-label="${dimensionLabels[dimension.id]}: ${value}"`)
    if (dimension.explanation) expect(html).toContain(dimension.explanation)
    for (const missing of dimension.missing_information) expect(html).toContain(missing)
  }
  expect([...html.matchAll(/data-dimension="([^"]+)"/g)].map((match) => match[1])).toEqual([
    'skills',
  ])
  expect(html).not.toContain('data-match-area="assessed"')
})

test('all unknown has no invented total or radar data points', () => {
  const score = createMatchScoreFixture()
  score.total = null
  score.dimensions = score.dimensions.map((dimension) => ({
    ...dimension,
    score: null,
    status: 'unknown',
  }))
  const html = renderToStaticMarkup(<MatchRadar score={score} />)
  expect(html).not.toContain('<circle ')
  expect(html).not.toContain('data-match-area="assessed"')
  expect(renderToStaticMarkup(<MatchScoreValue score={score} />)).not.toContain('/100')
  expect(renderToStaticMarkup(<MatchScoreSummary score={null} />)).toBe('')
})

test('an assessed zero stays numeric and only six assessed axes form a complete shape', () => {
  const score = createMatchScoreFixture()
  score.dimensions = score.dimensions.map((dimension, index) => ({
    ...dimension,
    score: index === 0 ? 0 : 80,
    status: 'assessed',
  }))
  const html = renderToStaticMarkup(<MatchRadar score={score} />)
  expect(html).toContain('aria-label="Skills: 0/100"')
  expect([...html.matchAll(/data-dimension="([^"]+)"/g)].map((match) => match[1])).toEqual(
    Object.keys(dimensionLabels),
  )
  expect(html).toContain('data-match-area="assessed"')
})

test('wire contract rejects missing axes and numeric unknowns before display', () => {
  const score = createMatchScoreFixture()
  expect(isMatchScore(score)).toBe(true)
  expect(isMatchScore({ ...score, dimensions: score.dimensions.slice(1) })).toBe(false)
  score.dimensions[1]!.score = 0
  expect(isMatchScore(score)).toBe(false)
})
