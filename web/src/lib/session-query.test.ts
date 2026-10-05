import { describe, expect, test } from 'bun:test'
import { rejects } from 'node:assert/strict'

import { QueryClient, QueryObserver } from '@tanstack/react-query'

import { createSessionFixture } from '../../tests/fixtures'
import type { ScoutSession } from './contracts'
import { createSessionClient } from './session-client'
import { latestSessionSnapshot, sessionKey, sessionQueryOptions } from './session-query'

const session = createSessionFixture()

describe('session query lifecycle', () => {
  test('late progress cannot replace more recent results from the same search run', () => {
    const newer = createSessionFixture({ outcome: 'running', run_id: 'run-1' })
    newer.progress = { ...newer.progress, sequence: 5, matched_count: 3 }
    const older = structuredClone(newer)
    older.progress = { ...older.progress, sequence: 2, matched_count: 0 }
    expect(latestSessionSnapshot(newer, older)).toBe(newer)
    expect(latestSessionSnapshot(older, newer)).toBe(newer)
    const nextRun = { ...older, run_id: 'run-2', revision: newer.revision + 1 }
    expect(latestSessionSnapshot(newer, nextRun)).toBe(nextRun)
  })
  test('fresh mutation responses are shared with queries without a duplicate GET', async () => {
    const cache = new QueryClient()
    let requests = 0
    const client = createSessionClient('/api/v1', () => {
      requests += 1
      return Promise.resolve(Response.json(session))
    })
    cache.setQueryData(sessionKey(session.session_id), session)
    const result = await cache.fetchQuery(sessionQueryOptions(client, session.session_id))
    expect(result).toEqual(session)
    expect(requests).toBe(0)
    await cache.invalidateQueries({ queryKey: sessionKey(session.session_id) })
    await cache.fetchQuery(sessionQueryOptions(client, session.session_id))
    expect(requests).toBe(1)
    cache.clear()
  })

  test('expired sessions fail without retrying a 404', async () => {
    const cache = new QueryClient()
    let requests = 0
    const client = createSessionClient('/api/v1', () => {
      requests += 1
      return Promise.resolve(Response.json({ detail: 'Session not found' }, { status: 404 }))
    })
    await rejects(cache.fetchQuery(sessionQueryOptions(client, 'missing')), {
      status: 404,
    })
    expect(requests).toBe(1)
    cache.clear()
  })

  test('transient GET failures retry once and recover', async () => {
    const cache = new QueryClient()
    let requests = 0
    const client = createSessionClient('/api/v1', () => {
      requests += 1
      return Promise.resolve(
        requests === 1
          ? Response.json({ detail: 'Unavailable' }, { status: 503 })
          : Response.json(session),
      )
    })
    const result = await cache.fetchQuery({
      ...sessionQueryOptions(client, session.session_id),
      retryDelay: 0,
    })
    expect(result).toEqual(session)
    expect(requests).toBe(2)
    cache.clear()
  })

  test('query cancellation reaches fetch and cannot commit a late response', async () => {
    const cache = new QueryClient()
    const requested = Promise.withResolvers<AbortSignal>()
    const pending = Promise.withResolvers<Response>()
    const client = createSessionClient('/api/v1', (_url, init) => {
      if (!init?.signal) throw new Error('Expected query cancellation signal')
      requested.resolve(init.signal)
      return pending.promise
    })
    const observer = new QueryObserver(cache, sessionQueryOptions(client, session.session_id))
    const unsubscribe = observer.subscribe(() => {})
    const signal = await requested.promise
    await cache.cancelQueries({ queryKey: sessionKey(session.session_id) })
    expect(signal.aborted).toBe(true)
    pending.resolve(Response.json(session))
    await pending.promise
    expect(cache.getQueryData(sessionKey(session.session_id))).toBeUndefined()
    unsubscribe()
    cache.clear()
  })

  test('late GET snapshots cannot regress accepted revisions or restore a running outcome after completion', async () => {
    for (const old of [
      createSessionFixture({ revision: 4, outcome: 'paused' }),
      createSessionFixture({ revision: 5, outcome: 'running' }),
    ]) {
      const cache = new QueryClient()
      const response = Promise.withResolvers<Response>()
      const client = createSessionClient('/api/v1', () => response.promise)
      const reading = cache.fetchQuery(sessionQueryOptions(client, old.session_id))
      const confirmed = createSessionFixture({
        session_id: old.session_id,
        revision: 5,
        outcome: 'completed',
      })
      cache.setQueryData(sessionKey(old.session_id), confirmed)
      response.resolve(Response.json(old))
      expect(await reading).toEqual(confirmed)
      expect(cache.getQueryData<ScoutSession>(sessionKey(old.session_id))).toEqual(confirmed)
      cache.clear()
    }
  })
})
