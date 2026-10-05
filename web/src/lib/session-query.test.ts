import { describe, expect, test } from 'bun:test'
import { rejects } from 'node:assert/strict'

import { QueryClient, QueryObserver } from '@tanstack/react-query'

import { createSessionFixture } from '../../tests/fixtures'
import { createSessionClient } from './session-client'
import { sessionKey, sessionQueryOptions } from './session-query'

const session = createSessionFixture()

describe('session query lifecycle', () => {
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
})
