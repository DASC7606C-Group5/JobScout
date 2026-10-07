import { describe, expect, test } from 'bun:test'

import { createSessionFixture } from '../../tests/fixtures'
import type { ScoutSession } from './contracts'
import { subscribeToSession, type SessionEventSource } from './session-events'

function connection() {
  let listener: ((event: MessageEvent<string>) => void) | undefined
  const source = {
    closed: false,
    onerror: null as SessionEventSource['onerror'],
    addEventListener: (_type: 'snapshot', callback: (event: MessageEvent<string>) => void) => {
      listener = callback
    },
    close() {
      this.closed = true
    },
  }
  return {
    source,
    send: (data: string) => listener?.(new MessageEvent('snapshot', { data })),
  }
}

describe('session event transport', () => {
  test('receives progress through reconnects and closes on the final result', () => {
    const stream = connection()
    const received: ScoutSession[] = []
    const errors: Error[] = []
    subscribeToSession(
      '/sessions/session-1/events',
      'session-1',
      {
        onSnapshot: (snapshot) => received.push(snapshot),
        onError: (error) => errors.push(error),
      },
      () => stream.source,
    )
    const running = createSessionFixture({ outcome: 'running', run_id: 'run-1' })
    stream.send(JSON.stringify(running))
    stream.source.onerror?.(new Event('error'))
    expect(errors[0]).toHaveProperty('code', 'connection_unavailable')
    expect(stream.source.closed).toBe(false)
    const updated = structuredClone(running)
    updated.progress.sequence = 8
    stream.send(JSON.stringify(updated))
    const complete = { ...updated, outcome: 'completed' as const }
    stream.send(JSON.stringify(complete))
    stream.send(JSON.stringify(running))
    expect(received).toEqual([running, updated, complete])
    expect(stream.source.closed).toBe(true)
  })

  test('invalid JSON, malformed snapshots and other session data never reach the cache', () => {
    for (const data of [
      'private malformed response',
      JSON.stringify({ session_id: 'session-1' }),
      JSON.stringify(createSessionFixture({ session_id: 'other-session' })),
    ]) {
      const stream = connection()
      const received: ScoutSession[] = []
      const errors: Error[] = []
      subscribeToSession(
        '/sessions/session-1/events',
        'session-1',
        {
          onSnapshot: (snapshot) => received.push(snapshot),
          onError: (error) => errors.push(error),
        },
        () => stream.source,
      )
      stream.send(data)
      expect(errors[0]).toHaveProperty('code', 'invalid_response')
      expect(errors[0]?.message).not.toContain('private')
      expect(received).toEqual([])
      expect(stream.source.closed).toBe(true)
    }
  })

  test('unsubscribing suppresses late messages and connection errors', () => {
    const stream = connection()
    const received: ScoutSession[] = []
    const errors: Error[] = []
    const close = subscribeToSession(
      '/sessions/session-1/events',
      'session-1',
      {
        onSnapshot: (snapshot) => received.push(snapshot),
        onError: (error) => errors.push(error),
      },
      () => stream.source,
    )
    close()
    stream.send(JSON.stringify(createSessionFixture()))
    stream.source.onerror?.(new Event('error'))
    expect(received).toEqual([])
    expect(errors).toEqual([])
    expect(stream.source.closed).toBe(true)
  })
})
