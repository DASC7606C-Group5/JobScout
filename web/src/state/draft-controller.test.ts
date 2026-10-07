import { describe, expect, test } from 'bun:test'

import { SessionHttpError } from '../lib/api-client'
import type { DraftResponse, SaveDraftRequest } from '../lib/contracts'
import { DraftController } from './draft-controller'
import {
  discardSessionDrafts,
  flushPendingDrafts,
  hasPendingDrafts,
  registerDraft,
} from './draft-navigation'

type Value = { message: string; choices: string[] }
const initial: Value = { message: '', choices: [] }
const record = (data: Value, revision = 1): DraftResponse<Value> => ({
  data,
  revision,
  updated_at: '2026-10-06T00:00:00Z',
})

describe('server draft lifecycle', () => {
  test('discarded drafts ignore late reads and cannot restore private cache data', async () => {
    for (const action of ['retry', 'reload', 'overwrite'] as const) {
      const reading = Promise.withResolvers<DraftResponse<Value>>()
      const committed: DraftResponse<Value>[] = []
      const controller = new DraftController(
        initial,
        async (request) => record(request.data),
        () => reading.promise,
        (response) => committed.push(response),
      )
      controller.update({ message: 'Private local draft', choices: [] })
      const pending = controller[action]()
      controller.discard()
      reading.resolve(record({ message: 'Private remote draft', choices: ['data'] }, 5))
      expect(await pending).toBe(true)
      expect(committed).toEqual([])
      expect(controller.getSnapshot().value).toEqual(initial)
      expect(controller.hasPending()).toBe(false)
    }
  })

  test('late load failures cannot reactivate a discarded draft', async () => {
    const reading = Promise.withResolvers<DraftResponse<Value>>()
    const controller = new DraftController(
      initial,
      async (request) => record(request.data),
      () => reading.promise,
    )
    const pending = controller.reload()
    controller.discard()
    reading.reject(new Error('Old account request failed'))
    expect(await pending).toBe(true)
    controller.loadFailed(new Error('Late query failure'))
    expect(controller.getSnapshot().status).toBe('saved')
    expect(controller.getSnapshot().error).toBeNull()
  })

  test('flush preserves raw supplied values and advances the independent revision', async () => {
    const requests: SaveDraftRequest<Value>[] = []
    const controller = new DraftController(
      initial,
      async (request) => {
        requests.push(request)
        return record(request.data, 5)
      },
      async () => record(initial),
    )
    controller.hydrate(record(initial, 4))
    const value = { message: '  想在香港，保留原文  ', choices: ['React', '数据分析'] }
    const supplied = structuredClone(value)
    controller.update(value)
    value.choices.push('Later mutation')
    expect(await controller.flush()).toBe(true)
    expect(requests[0]?.data).toEqual(supplied)
    expect(requests[0]?.expected_revision).toBe(4)
    expect(controller.getSnapshot().value).toEqual(supplied)
    expect(controller.getSnapshot().revision).toBe(5)
    expect(controller.hasPending()).toBe(false)
  })

  test('does not save during IME composition; flush waits for composition to finish', async () => {
    const requests: SaveDraftRequest<Value>[] = []
    const controller = new DraftController(
      initial,
      async (request) => {
        requests.push(request)
        return record(request.data)
      },
      async () => record(initial),
      undefined,
      5,
    )
    controller.hydrate(record(initial, 0))
    controller.setComposing(true)
    expect(await controller.flush()).toBe(false)
    controller.update({ message: '香港', choices: [] })
    await new Promise((resolve) => setTimeout(resolve, 15))
    expect(await controller.flush()).toBe(false)
    expect(requests).toEqual([])
    controller.setComposing(false)
    expect(await controller.flush()).toBe(true)
    expect(requests[0]?.data.message).toBe('香港')
  })

  test('retries a lost save response with the identical request ID and payload', async () => {
    const requests: SaveDraftRequest<Value>[] = []
    const controller = new DraftController(
      initial,
      async (request) => {
        requests.push(structuredClone(request))
        if (requests.length === 1)
          throw new Error('Connection failed after the server accepted the draft')
        return record(request.data)
      },
      async () => record(initial),
    )
    controller.hydrate(record(initial, 0))
    controller.update({ message: 'Keep my edits', choices: ['frontend'] })
    expect(await controller.flush()).toBe(false)
    expect(controller.getSnapshot().value.message).toBe('Keep my edits')
    expect(controller.getSnapshot().status).toBe('error')
    expect(await controller.retry()).toBe(true)
    expect(requests[1]).toEqual(requests[0])
  })

  test('a save response cannot replace text edited while that request was pending', async () => {
    const first = Promise.withResolvers<DraftResponse<Value>>()
    const requests: SaveDraftRequest<Value>[] = []
    const controller = new DraftController(
      initial,
      (request) => {
        requests.push(structuredClone(request))
        return requests.length === 1 ? first.promise : Promise.resolve(record(request.data, 2))
      },
      async () => record(initial),
    )
    controller.hydrate(record(initial, 0))
    controller.update({ message: 'First edit', choices: [] })
    const saving = controller.flush()
    controller.update({ message: 'Newer input', choices: ['data'] })
    first.resolve(record({ message: 'First edit', choices: [] }, 1))
    expect(await saving).toBe(true)
    expect(controller.getSnapshot().value).toEqual({ message: 'Newer input', choices: ['data'] })
    expect(requests[1]?.data.message).toBe('Newer input')
    expect(requests[1]?.expected_revision).toBe(1)
  })

  test('a delayed older GET cannot replace an edit that was already saved at a newer revision', async () => {
    const earlier = { message: 'Earlier shared snapshot', choices: ['data'] }
    const latest = { message: 'New saved text', choices: ['React'] }
    const controller = new DraftController(
      initial,
      async (request) => record(request.data, 3),
      async () => record(earlier, 2),
    )
    controller.hydrate(record(earlier, 2))
    controller.update(latest)
    expect(await controller.flush()).toBe(true)
    controller.hydrate(record(earlier, 2))
    expect(controller.getSnapshot().value).toEqual(latest)
    expect(controller.getSnapshot().revision).toBe(3)
  })

  test('a stale shared draft keeps local edits until explicit overwrite or reload', async () => {
    const local = { message: 'My local draft', choices: ['frontend'] }
    const remote = { message: 'Shared newer draft', choices: ['data'] }
    const requests: SaveDraftRequest<Value>[] = []
    const controller = new DraftController(
      initial,
      async (request) => {
        requests.push(request)
        if (request.expected_revision !== 3) throw new SessionHttpError(409, 'draft_conflict')
        return record(request.data, 4)
      },
      async () => record(remote, 3),
    )
    controller.hydrate(record(initial, 1))
    controller.update(local)
    expect(await controller.flush()).toBe(false)
    expect(controller.getSnapshot().status).toBe('conflict')
    controller.hydrate(record(remote, 3))
    expect(controller.getSnapshot().value).toEqual(local)
    expect(await controller.flush()).toBe(false)
    expect(requests).toHaveLength(1)
    expect(await controller.overwrite()).toBe(true)
    expect(requests[1]?.data).toEqual(local)
    expect(requests[1]?.expected_revision).toBe(3)
    controller.update({ message: 'Discard explicitly', choices: [] })
    expect(await controller.reload()).toBe(true)
    expect(controller.getSnapshot().value).toEqual(remote)
    expect(controller.hasPending()).toBe(false)
  })

  test('retrying initial-load failure cannot silently overwrite an existing shared draft', async () => {
    const local = { message: 'Typed while offline', choices: [] }
    const remote = { message: 'Existing shared text', choices: ['data'] }
    const requests: SaveDraftRequest<Value>[] = []
    const controller = new DraftController(
      initial,
      async (request) => {
        requests.push(request)
        return record(request.data, 3)
      },
      async () => record(remote, 2),
    )
    controller.loadFailed(new Error('Offline'))
    controller.update(local)
    expect(controller.getSnapshot().status).toBe('error')
    expect(await controller.retry()).toBe(false)
    expect(requests).toEqual([])
    expect(controller.getSnapshot().status).toBe('conflict')
    expect(controller.getSnapshot().value).toEqual(local)
    expect(await controller.overwrite()).toBe(true)
    expect(requests[0]?.expected_revision).toBe(2)
    expect(requests[0]?.data).toEqual(local)
  })

  test('accepted session revision discards its draft without saving it again during navigation', async () => {
    const requests: string[] = []
    const sessionDraft = new DraftController(
      initial,
      async (request) => {
        requests.push('session')
        return record(request.data)
      },
      async () => record(initial),
    )
    const workspaceDraft = new DraftController(
      initial,
      async (request) => {
        requests.push('workspace')
        return record(request.data)
      },
      async () => record(initial),
    )
    sessionDraft.hydrate(record(initial, 0))
    workspaceDraft.hydrate(record(initial, 0))
    const releaseSession = registerDraft(sessionDraft, '/sessions/session-1/drafts/2/summary')
    const releaseWorkspace = registerDraft(workspaceDraft, '/workspace/draft')
    try {
      sessionDraft.update({ message: 'Accepted summary', choices: [] })
      workspaceDraft.update({ message: 'Independent new search', choices: [] })
      discardSessionDrafts('session-1', 2)
      expect(await flushPendingDrafts()).toBe(true)
      expect(requests).toEqual(['workspace'])
      expect(workspaceDraft.getSnapshot().value.message).toBe('Independent new search')
      expect(hasPendingDrafts()).toBe(false)
    } finally {
      releaseSession()
      releaseWorkspace()
    }
  })

  test('input supplied while a reload was pending is preserved for explicit conflict recovery', async () => {
    const reading = Promise.withResolvers<DraftResponse<Value>>()
    const controller = new DraftController(
      initial,
      async (request) => record(request.data),
      () => reading.promise,
    )
    controller.hydrate(record(initial, 1))
    controller.update({ message: 'Earlier local input', choices: [] })
    const reloading = controller.reload()
    controller.update({ message: 'Typed after reload began', choices: ['React'] })
    reading.resolve(record({ message: 'Remote draft', choices: [] }, 2))
    expect(await reloading).toBe(false)
    expect(controller.getSnapshot().value).toEqual({
      message: 'Typed after reload began',
      choices: ['React'],
    })
    expect(controller.getSnapshot().status).toBe('conflict')
    controller.discard()
  })

  test('failed draft flush blocks navigation and leaves every supplied value available', async () => {
    const controller = new DraftController(
      initial,
      async () => {
        throw new Error('Offline')
      },
      async () => record(initial),
    )
    controller.hydrate(record(initial, 0))
    const release = registerDraft(controller, '/workspace/draft')
    try {
      controller.update({ message: 'Do not lose me', choices: ['数据分析'] })
      expect(await flushPendingDrafts()).toBe(false)
      expect(hasPendingDrafts()).toBe(true)
      expect(controller.getSnapshot().value).toEqual({
        message: 'Do not lose me',
        choices: ['数据分析'],
      })
    } finally {
      controller.discard()
      release()
    }
  })
})
