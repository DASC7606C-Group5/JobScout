import { expect, test } from 'bun:test'

import { createUserProfileFixture } from '../../tests/fixtures'
import {
  summaryDirectionError,
  summaryDraft,
  summaryFields,
  summaryUpdates,
} from './search-summary'

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

test('confirmation editing requires an explicit choice when the direction list exceeds three', () => {
  const original = summaryDraft(createUserProfileFixture())
  const draft = { ...original, target_directions: '前端开发\n数据分析，产品设计、项目管理' }
  expect(summaryDirectionError(draft)).toBeTruthy()
  expect(summaryUpdates(original, draft, editable).target_directions).toEqual([
    '前端开发',
    '数据分析',
    '产品设计',
    '项目管理',
  ])
  expect(
    summaryDirectionError({ ...draft, target_directions: '前端开发\n数据分析，产品设计' }),
  ).toBeNull()
  expect(summaryDirectionError({ ...draft, target_directions: '前端开发\n前端开发' })).toBeNull()
})
