import { describe, expect, test } from 'bun:test'

import {
  createProfileFixture,
  createRecommendationFixture,
  createSessionFixture,
} from '../../tests/fixtures'
import type { UserProfile } from '../lib/contracts'
import { summaryDraft } from '../lib/search-summary'
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
    expect(store.getState().announcement).toContain('Removed from saved jobs')
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

  test('retains independent form drafts only within the current session revision', () => {
    const store = createScoutStore()
    const clarification = {
      values: { role: ['frontend'] },
      skipped: ['salary'],
      message: '想在香港',
    }
    store.getState().saveSessionDraft('session-1:2', 'clarification', clarification)
    clarification.values.role.push('backend')
    expect(store.getState().sessionDrafts?.values.clarification?.values.role).toEqual(['frontend'])
    const summary = { fields: summaryDraft(createSessionFixture().profile!), message: '补充条件' }
    store.getState().saveSessionDraft('session-1:2', 'summary', summary)
    expect(store.getState().sessionDrafts?.values.clarification?.message).toBe('想在香港')
    expect(store.getState().sessionDrafts?.values.summary).toEqual(summary)
    store.getState().saveSessionDraft('session-1:3', 'summary', summary)
    expect(store.getState().sessionDrafts?.values.clarification).toBeUndefined()
    store.getState().saveSessionDraft('session-2:3', 'clarification', clarification)
    expect(store.getState().sessionDrafts?.values.summary).toBeUndefined()
    store.getState().clearSessionDrafts()
    expect(store.getState().sessionDrafts).toBeNull()
    expect(createScoutStore().getState().sessionDrafts).toBeNull()
  })
})
