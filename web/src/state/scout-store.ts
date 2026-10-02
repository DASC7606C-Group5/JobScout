import { createStore } from 'zustand/vanilla'

import type {
  DemoScenario,
  RecommendationItem,
  ScoutInput,
  ScoutSession,
  SessionClient,
} from '../lib/contracts'
import { createProfileDraft, type ProfileFormValues } from '../lib/profile-form'

type Operation =
  | { kind: 'start'; input: ScoutInput; scenario: DemoScenario }
  | {
      kind: 'answer'
      session: ScoutSession
      answers: Record<string, string>
      scenario: DemoScenario
    }
  | { kind: 'retry'; session: ScoutSession }

export interface ScoutState {
  draft: ProfileFormValues
  answers: Record<string, string>
  scenario: DemoScenario
  session: ScoutSession | null
  saved: RecommendationItem[]
  busy: boolean
  error: string | null
  announcement: string
  saveDraft: (draft: ProfileFormValues) => void
  saveAnswers: (answers: Record<string, string>) => void
  setScenario: (scenario: DemoScenario) => void
  toggleSaved: (item: RecommendationItem) => void
  start: (input: ScoutInput) => Promise<void>
  answer: (answers: Record<string, string>) => Promise<void>
  retry: () => Promise<void>
  edit: () => void
}

export function createScoutStore(client: SessionClient) {
  let requestId = 0
  let lastOperation: Operation | null = null

  return createStore<ScoutState>()((set, get) => {
    async function execute(operation: Operation) {
      if (get().busy) return
      const id = ++requestId
      lastOperation = operation
      set({ busy: true, error: null })
      let session: ScoutSession
      try {
        session = await runOperation(client, operation)
      } catch {
        if (id === requestId) set({ busy: false, error: '操作未完成，资料已保留，请重试。' })
        return
      }
      // Editing starts a new search; a late response must not overwrite its draft.
      if (id !== requestId) return
      set((state) => ({
        session,
        busy: false,
        draft: {
          ...state.draft,
          directions: session.profile.target_directions.join('，'),
          preferences: { ...session.profile.preferences },
        },
      }))
    }

    return {
      draft: createProfileDraft(),
      answers: {},
      scenario: 'normal',
      session: null,
      saved: [],
      busy: false,
      error: null,
      announcement: '',
      saveDraft: (draft) => set({ draft: { ...draft, preferences: { ...draft.preferences } } }),
      saveAnswers: (answers) => set({ answers }),
      setScenario: (scenario) => {
        if (!get().busy && !get().session) set({ scenario })
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
      start: async (input) => {
        if (get().busy) return
        set({
          answers: {},
          draft: {
            description: input.description,
            resume: input.resume,
            directions: input.target_directions.join('，'),
            preferences: { ...input.preferences },
          },
        })
        await execute({ kind: 'start', input, scenario: get().scenario })
      },
      answer: async (answers) => {
        const { session, scenario, busy } = get()
        if (!session || busy) return
        set({ answers })
        await execute({ kind: 'answer', session, answers, scenario })
      },
      retry: async () => {
        const { session, error } = get()
        if (error && lastOperation) await execute(lastOperation)
        else if (session) await execute({ kind: 'retry', session })
      },
      edit: () => {
        requestId += 1
        lastOperation = null
        set({ session: null, busy: false, error: null, answers: {} })
      },
    }
  })
}

function runOperation(client: SessionClient, operation: Operation) {
  switch (operation.kind) {
    case 'start':
      return client.start(operation.input, operation.scenario)
    case 'answer':
      return client.answer(operation.session, operation.answers, operation.scenario)
    case 'retry':
      return client.retry(operation.session)
  }
}

export type ScoutStore = ReturnType<typeof createScoutStore>
