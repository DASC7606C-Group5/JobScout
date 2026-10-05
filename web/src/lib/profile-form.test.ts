import { expect, test } from 'bun:test'

import { createProfileFixture } from '../../tests/fixtures'
import { createProfileDraft, parseDirections, toScoutInput } from './profile-form'

test('normalizes form fields without changing the raw editable draft', () => {
  const draft = createProfileFixture()
  draft.description = '  开发经历  '
  draft.directions = ' 前端开发\n数据分析\n前端开发\n '
  draft.preferences.location_unrestricted = true
  draft.preferences.work_mode = ''
  const original = structuredClone(draft)
  const input = toScoutInput(draft)
  expect(input.description).toBe('开发经历')
  expect(input.target_directions).toEqual(['前端开发', '数据分析'])
  expect(input.preferences.location).toBeNull()
  expect(input.preferences.work_mode).toBeNull()
  expect(draft).toEqual(original)
  expect(input).not.toHaveProperty('directions')
})

test('resume-only input and absent optional preferences preserve the contract', () => {
  const draft = createProfileDraft()
  draft.resume = { name: 'resume.txt', text: 'React 项目经历' }
  draft.directions = ' \n \n '
  const input = toScoutInput(draft)
  expect(input.resume).toEqual(draft.resume)
  expect(input.target_directions).toEqual([])
  expect(input.preferences.location).toBeNull()
  expect(input.preferences.employment_type).toBeNull()
})

test('direction drafts separate lines while preserving compound roles', () => {
  expect(
    parseDirections('前端开发\n数据分析，产品设计、项目管理\nEngineer, AI/ML\n前端开发'),
  ).toEqual(['前端开发', '数据分析，产品设计、项目管理', 'Engineer, AI/ML'])
})

test('search submissions preserve requested result counts and composite raw conditions', () => {
  for (const result_count of [5, 10, 20]) {
    const draft = createProfileFixture()
    draft.search_options.result_count = result_count
    draft.preferences.location = '上海或深圳，排除浦东'
    draft.preferences.employment_type = 'full-time or internship, excluding contract'
    const input = toScoutInput(draft)
    expect(input.search_options).toEqual({ result_count })
    expect(input.preferences.location).toBe(draft.preferences.location)
    expect(input.preferences.employment_type).toBe(draft.preferences.employment_type)
  }
})
