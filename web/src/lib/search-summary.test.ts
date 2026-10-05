import { expect, test } from 'bun:test'

import { createUserProfileFixture } from '../../tests/fixtures'
import { summaryDraft, summaryFields, summaryUpdates } from './search-summary'

const editable = summaryFields.map(([key]) => key)

test('summary posts changed flat keys only and splits arrays', () => {
  const original = summaryDraft(createUserProfileFixture())
  expect(summaryUpdates(original, original, editable)).toEqual({})
  expect(
    summaryUpdates(
      original,
      { ...original, skills: 'React\nSQL，SQL', 'preferences.location': ' 深圳 ' },
      editable,
    ),
  ).toEqual({ skills: ['React', 'SQL'], 'preferences.location': '深圳' })
})

test('unrestricted fields explicitly clear constrained values; noneditable fields remain unchanged', () => {
  const original = summaryDraft(createUserProfileFixture())
  expect(
    summaryUpdates(
      original,
      {
        ...original,
        'preferences.location_unrestricted': true,
        'preferences.employment_type_unrestricted': true,
      },
      editable,
    ),
  ).toEqual({
    'preferences.location_unrestricted': true,
    'preferences.location': null,
    'preferences.employment_type_unrestricted': true,
    'preferences.employment_type': null,
  })
  expect(summaryUpdates(original, { ...original, skills: 'SQL' }, [])).toEqual({})
})
