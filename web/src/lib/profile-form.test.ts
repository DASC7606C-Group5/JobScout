import { expect, test } from 'bun:test'

import { createProfileFixture } from '../../tests/fixtures'
import { createProfileDraft, toScoutInput } from './profile-form'

test('normalizes form fields without changing the raw editable draft', () => {
  const draft = createProfileFixture()
  draft.description = '  开发经历  '
  draft.directions = ' 前端开发，数据分析、前端开发,, '
  draft.preferences.location_unrestricted = true
  draft.preferences.work_mode = ''
  const input = toScoutInput(draft)
  expect(input.description).toBe('开发经历')
  expect(input.target_directions).toEqual(['前端开发', '数据分析'])
  expect(input.preferences.location).toBeNull()
  expect(input.preferences.work_mode).toBeNull()
  expect(draft.preferences.location).toBe('香港')
  expect(draft.description).toBe('  开发经历  ')
  expect(input).not.toHaveProperty('directions')
})

test('resume-only input and absent optional preferences preserve the contract', () => {
  const draft = createProfileDraft()
  draft.resume = { name: 'resume.txt', text: 'React 项目经历' }
  draft.directions = '， 、 ,'
  const input = toScoutInput(draft)
  expect(input.resume).toEqual(draft.resume)
  expect(input.target_directions).toEqual([])
  expect(input.preferences.location).toBeNull()
  expect(input.preferences.employment_type).toBeNull()
})
