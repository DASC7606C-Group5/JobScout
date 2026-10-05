import { createStore } from 'zustand/vanilla'

import type { RecommendationItem, UserProfile } from '../lib/contracts'
import { createProfileDraft, type ProfileFormValues } from '../lib/profile-form'
import type { SessionDrafts, SessionDraftSection, SessionDraftValues } from './use-session-draft'

export interface ScoutState {
  draft: ProfileFormValues
  answers: Record<string, string>
  sessionDrafts: SessionDrafts | null
  saved: RecommendationItem[]
  announcement: string
  saveDraft: (draft: ProfileFormValues) => void
  saveAnswers: (answers: Record<string, string>) => void
  saveSessionDraft: <K extends SessionDraftSection>(
    scope: string,
    section: K,
    value: SessionDraftValues[K],
  ) => void
  clearSessionDrafts: () => void
  applyProfile: (profile: UserProfile | null) => void
  toggleSaved: (item: RecommendationItem) => void
}

export function createScoutStore() {
  return createStore<ScoutState>()((set) => ({
    draft: createProfileDraft(),
    answers: {},
    sessionDrafts: null,
    saved: [],
    announcement: '',
    saveDraft: (draft) => set({ draft: { ...draft, preferences: { ...draft.preferences } } }),
    saveAnswers: (answers) => set({ answers: { ...answers } }),
    saveSessionDraft: (scope, section, value) =>
      set((state) => ({
        sessionDrafts: {
          scope,
          values: {
            ...(state.sessionDrafts?.scope === scope ? state.sessionDrafts.values : {}),
            [section]: structuredClone(value),
          },
        },
      })),
    clearSessionDrafts: () => set({ sessionDrafts: null }),
    applyProfile: (profile) => {
      if (!profile) return
      set((state) => ({
        draft: {
          ...state.draft,
          directions: profile.target_directions.join('，'),
          preferences: { ...profile.preferences },
        },
      }))
    },
    toggleSaved: (item) =>
      set((state) => {
        const exists = state.saved.some((entry) => entry.job.job_id === item.job.job_id)
        return {
          saved: exists
            ? state.saved.filter((entry) => entry.job.job_id !== item.job.job_id)
            : [...state.saved, item],
          announcement: `${exists ? '已取消收藏' : '已收藏'}：${item.job.title}`,
        }
      }),
  }))
}

export type ScoutStore = ReturnType<typeof createScoutStore>
