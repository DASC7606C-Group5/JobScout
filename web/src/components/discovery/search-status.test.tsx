import { expect, test } from 'bun:test'

import { renderToStaticMarkup } from 'react-dom/server'

import { createSessionFixture } from '../../../tests/fixtures'
import { SearchLoading } from './search-status'

test('search activity preserves public counts and hides internal events', () => {
  const session = createSessionFixture({
    outcome: 'running',
    current_stage: 'search',
    run_id: 'run-1',
  })
  session.profile!.search_options.result_count = 5
  session.progress.matched_count = 12
  session.progress.analyzed_count = 12
  session.progress.events = [
    {
      sequence: 1,
      action: 'unknown_private_tool',
      message: 'private-agent-path budget=60',
      source: 'internal-source-code',
    },
  ]
  const loading = renderToStaticMarkup(
    <SearchLoading session={session} onStop={() => {}} stopping={false} />,
  )
  expect(loading).not.toContain('private-agent-path')
  expect(loading).not.toContain('unknown_private_tool')
  expect(loading).not.toContain('internal-source-code')
  expect(session.progress.matched_count).toBe(12)
})
