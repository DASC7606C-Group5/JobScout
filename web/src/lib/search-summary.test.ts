import { expect, test } from 'bun:test'

import { createUserProfileFixture } from '../../tests/fixtures'
import { summaryDraft, summaryFields, summaryUpdates } from './search-summary'

const editable = summaryFields.map(([key]) => key)

test('summary edits preserve punctuation within qualifications, experience and compound roles', () => {
  const original = summaryDraft(createUserProfileFixture())
  const education = 'BSc, Computer Science\nHigher Diploma; awarded with distinction'
  const target_directions = 'Engineer, AI/ML\nUI/UX Designer'
  expect(summaryUpdates(original, { ...original, education, target_directions }, editable)).toEqual(
    {
      education: ['BSc, Computer Science', 'Higher Diploma; awarded with distinction'],
      target_directions: ['Engineer, AI/ML', 'UI/UX Designer'],
    },
  )
})

test('summary posts changed flat keys only and splits arrays', () => {
  const original = summaryDraft(createUserProfileFixture())
  expect(summaryUpdates(original, original, editable)).toEqual({})
  expect(
    summaryUpdates(
      original,
      { ...original, skills: 'React\nSQL\nSQL', 'preferences.location': ' 深圳 ' },
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

test('confirmation editing preserves more than three directions', () => {
  const original = summaryDraft(createUserProfileFixture())
  const draft = { ...original, target_directions: '前端开发\n数据分析\n产品设计\n项目管理' }
  expect(summaryUpdates(original, draft, editable).target_directions).toEqual([
    '前端开发',
    '数据分析',
    '产品设计',
    '项目管理',
  ])
})
