import { expect, test } from 'bun:test'

import { renderToStaticMarkup } from 'react-dom/server'

import { createUserProfileFixture } from '../../../tests/fixtures'
import { summaryDraft, summaryFields } from '../../lib/search-summary'
import { SummaryValues } from './profile-summary'

test('summaries preserve every supplied direction and parsed exclusion', () => {
  const profile = createUserProfileFixture()
  profile.target_directions = [
    'Engineer, AI/ML',
    'UI/UX Designer',
    'Data analyst',
    'Product designer',
  ]
  profile.preferences.locations.excluded = [
    {
      ...profile.preferences.locations.included[0]!,
      id: 'excluded-place',
      name: 'Excluded district',
    },
  ]
  const html = renderToStaticMarkup(
    <SummaryValues fields={[...summaryFields]} draft={summaryDraft(profile)} profile={profile} />,
  )
  for (const direction of profile.target_directions) expect(html).toContain(direction)
  expect(html).toContain('Excluded district')
})

test('editing another field preserves interpreted conditions, while a location edit replaces stale interpretation', () => {
  const profile = createUserProfileFixture()
  profile.preferences.locations.excluded = [
    {
      ...profile.preferences.locations.included[0]!,
      id: 'excluded-place',
      name: 'Original excluded district',
    },
  ]
  const draft = { ...summaryDraft(profile), target_directions: 'New direction' }
  const fields = summaryFields.filter(([key]) => key === 'preferences.location')
  const before = renderToStaticMarkup(
    <SummaryValues fields={fields} draft={draft} profile={profile} />,
  )
  expect(before).toContain('Hong Kong')
  expect(before).toContain('Original excluded district')
  draft['preferences.location'] = 'Shenzhen excluding Nanshan'
  const after = renderToStaticMarkup(
    <SummaryValues fields={fields} draft={draft} profile={profile} />,
  )
  expect(after).toContain('Shenzhen excluding Nanshan')
  expect(after).not.toContain('Hong Kong')
  expect(after).not.toContain('Original excluded district')
})
