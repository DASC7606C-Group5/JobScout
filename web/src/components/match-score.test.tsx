import { expect, test } from 'bun:test'

import { renderToStaticMarkup } from 'react-dom/server'

import { createMatchScoreFixture } from '../../tests/fixtures'
import { dimensionLabels } from '../lib/matching-contracts'
import { MatchRadar, MatchScoreValue } from './match-score'

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
})

test('unknown assessments do not display an invented score', () => {
  const score = createMatchScoreFixture()
  score.total = null
  score.dimensions = score.dimensions.map((dimension) => ({
    ...dimension,
    score: null,
    status: 'unknown',
  }))
  const html = renderToStaticMarkup(<MatchRadar score={score} />)
  expect(html).not.toContain('/100')
  expect(renderToStaticMarkup(<MatchScoreValue score={score} />)).not.toContain('/100')
})

test('dimension explanations stand alone while missing facts explain dimensions without one', () => {
  const score = createMatchScoreFixture()
  score.dimensions[0]!.missing_information = ['Additional detail about the interface']
  const html = renderToStaticMarkup(<MatchRadar score={score} />)
  expect(html).toContain(score.dimensions[0]!.explanation)
  expect(html).not.toContain(score.dimensions[0]!.missing_information[0]!)
  expect(html).toContain(score.dimensions[1]!.missing_information[0]!)
})

test('an assessed zero stays numeric', () => {
  const score = createMatchScoreFixture()
  score.dimensions = score.dimensions.map((dimension, index) => ({
    ...dimension,
    score: index === 0 ? 0 : 80,
    status: 'assessed',
  }))
  const html = renderToStaticMarkup(<MatchRadar score={score} />)
  expect(html).toContain('aria-label="Skills: 0/100"')
})
