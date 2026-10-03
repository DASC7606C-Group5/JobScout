import { describe, expect, test } from 'bun:test'

import { createProfileFixture, createRecommendationFixture } from '../../tests/fixtures'
import type { UserProfile } from '../lib/contracts'
import { createScoutStore } from './scout-store'

describe('workspace state', () => {
  test('retains raw drafts and favorites in isolated workspaces', () => {
    const store = createScoutStore()
    const draft = { ...createProfileFixture(), directions: '前端开发， 数据分析，' }
    store.getState().saveDraft(draft)
    draft.preferences.location = '深圳'
    expect(store.getState().draft.directions).toBe('前端开发， 数据分析，')
    expect(store.getState().draft.preferences.location).toBe('香港')
    const item = createRecommendationFixture()
    store.getState().toggleSaved(item)
    expect(store.getState().saved).toEqual([item])
    expect(createScoutStore().getState().saved).toEqual([])
    store.getState().toggleSaved(item)
    expect(store.getState().saved).toEqual([])
    expect(store.getState().announcement).toContain('已取消收藏')
  })

  test('merges the returned profile without replacing the description or resume', () => {
    const store = createScoutStore()
    const draft = {
      ...createProfileFixture(),
      resume: { name: 'resume.txt', text: 'React 项目经历' },
    }
    store.getState().saveDraft(draft)
    const profile: UserProfile = {
      profile_id: 'profile-1',
      source: { resume: true, description: true },
      education: [],
      skills: [],
      internships: [],
      projects: [],
      target_directions: ['数据分析'],
      preferences: { ...draft.preferences, work_mode: 'remote' },
      confirmed_fields: [],
      missing_required_fields: [],
      conflicts: [],
    }
    store.getState().applyProfile(profile)
    profile.preferences.location = '深圳'
    expect(store.getState().draft.directions).toBe('数据分析')
    expect(store.getState().draft.preferences.work_mode).toBe('remote')
    expect(store.getState().draft.preferences.location).toBe('香港')
    expect(store.getState().draft.description).toBe(draft.description)
    expect(store.getState().draft.resume).toEqual(draft.resume)
    store.getState().applyProfile(null)
    expect(store.getState().draft.directions).toBe('数据分析')
  })

  test('keeps dotted answer field names flat and copies the answer draft', () => {
    const store = createScoutStore()
    const answers = { 'preferences.work_mode': '远程' }
    store.getState().saveAnswers(answers)
    answers['preferences.work_mode'] = '不限'
    expect(store.getState().answers).toEqual({ 'preferences.work_mode': '远程' })
    store.getState().saveAnswers({})
    expect(store.getState().answers).toEqual({})
  })
})
