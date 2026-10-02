import { describe, expect, test } from 'bun:test'

import type { ScoutSession, SessionClient } from '../lib/contracts'
import { createExampleDraft, toScoutInput } from '../lib/profile-form'
import { createDemoClient } from '../lib/session-client'
import { createScoutStore } from './scout-store'

const input = toScoutInput(createExampleDraft())

describe('workspace state', () => {
  test('retains raw draft and favorites across session edits, with isolated workspaces', async () => {
    const store = createScoutStore(createDemoClient(0))
    const draft = { ...createExampleDraft(), directions: '前端开发， 数据分析，' }
    store.getState().saveDraft(draft)
    draft.preferences.location = '深圳'
    expect(store.getState().draft.directions).toBe('前端开发， 数据分析，')
    expect(store.getState().draft.preferences.location).toBe('香港')
    await store.getState().start(input)
    const item = store.getState().session?.recommendation?.jobs[0]
    if (!item) throw new Error('Expected a recommendation')
    store.getState().toggleSaved(item)
    store.getState().edit()
    expect(store.getState().session).toBeNull()
    expect(store.getState().saved).toEqual([item])
    expect(store.getState().draft.description).toBe(input.description)
    expect(createScoutStore(createDemoClient(0)).getState().saved).toEqual([])
    store.getState().toggleSaved(item)
    expect(store.getState().saved).toEqual([])
    expect(store.getState().announcement).toContain('已取消收藏')
  })

  test('clarification merges the returned profile into the editable draft', async () => {
    const store = createScoutStore(createDemoClient(0))
    store.getState().setScenario('clarify')
    await store.getState().start(input)
    store.getState().saveAnswers({ 'preferences.work_mode': '远程' })
    expect(store.getState().answers['preferences.work_mode']).toBe('远程')
    await store.getState().answer(store.getState().answers)
    expect(store.getState().session?.current_stage).toBe('completed')
    expect(store.getState().draft.preferences.work_mode).toBe('remote')
    store.getState().edit()
    expect(store.getState().draft.preferences.work_mode).toBe('remote')
    expect(store.getState().answers).toEqual({})
  })

  test('retries a transport failure with the original operation and retains input', async () => {
    const demo = createDemoClient(0)
    let attempts = 0
    const client: SessionClient = {
      ...demo,
      start: async (data, scenario) => {
        attempts += 1
        if (attempts === 1) throw new Error('Offline')
        return demo.start(data, scenario)
      },
    }
    const store = createScoutStore(client)
    await store.getState().start(input)
    expect(store.getState().busy).toBe(false)
    expect(store.getState().error).toBeTruthy()
    expect(store.getState().draft.description).toBe(input.description)
    await store.getState().retry()
    expect(attempts).toBe(2)
    expect(store.getState().error).toBeNull()
    expect(store.getState().session?.current_stage).toBe('completed')
  })

  test('workflow failure recovers without replacing the session identity', async () => {
    const store = createScoutStore(createDemoClient(0))
    store.getState().setScenario('error')
    await store.getState().start(input)
    const sessionId = store.getState().session?.session_id
    expect(store.getState().session?.current_stage).toBe('failed')
    await store.getState().retry()
    expect(store.getState().session?.current_stage).toBe('completed')
    expect(store.getState().session?.session_id).toBe(sessionId)
  })

  test('rejects duplicate submissions and ignores a response after editing', async () => {
    const deferred = Promise.withResolvers<ScoutSession>()
    let starts = 0
    const store = createScoutStore({
      ...createDemoClient(0),
      start: () => {
        starts += 1
        return deferred.promise
      },
    })
    const request = store.getState().start(input)
    await store.getState().start(input)
    store.getState().setScenario('error')
    expect(starts).toBe(1)
    expect(store.getState().busy).toBe(true)
    expect(store.getState().scenario).toBe('normal')
    store.getState().edit()
    store.getState().saveDraft({ ...createExampleDraft(), description: '新草稿' })
    deferred.resolve(await createDemoClient(0).start(input, 'normal'))
    await request
    expect(store.getState().session).toBeNull()
    expect(store.getState().busy).toBe(false)
    expect(store.getState().draft.description).toBe('新草稿')
  })
})
