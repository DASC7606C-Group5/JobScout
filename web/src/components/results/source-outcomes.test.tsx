import { expect, test } from 'bun:test'

import { renderToStaticMarkup } from 'react-dom/server'

import type { SourceOutcome } from '../../lib/contracts'
import { SourceOutcomes } from './source-outcomes'

const outcome: SourceOutcome = {
  request_index: 0,
  target_direction: '前端开发',
  source: 'JobsDB',
  candidate_count: 3,
  returned_count: 0,
  incomplete_count: 0,
  excerpt_count: 0,
  elapsed_seconds: 1,
  status: 'success',
}

test('source coverage distinguishes an empty successful search from an outage', () => {
  const html = renderToStaticMarkup(
    <SourceOutcomes outcomes={[outcome, { ...outcome, source: 'Liepin', status: 'blocked' }]} />,
  )
  expect(html).toContain('检索成功，无结果')
  expect(html).toContain('访问受限')
  expect(html).toContain('collapse-content')
  expect(html).not.toContain('open=""')
})

test('source coverage includes incomplete and excerpt counts without displaying unknown status codes', () => {
  const html = renderToStaticMarkup(
    <SourceOutcomes
      outcomes={[
        {
          ...outcome,
          returned_count: 3,
          incomplete_count: 1,
          excerpt_count: 2,
          status: 'new_status',
        },
      ]}
    />,
  )
  expect(html).toContain('3 个结果')
  expect(html).toContain('2 份仅有摘要')
  expect(html).toContain('1 份信息待补充')
  expect(html).toContain('检索状态待确认')
  expect(html).not.toContain('new_status')
})
