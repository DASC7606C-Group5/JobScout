import { describe, expect, test } from 'bun:test'
import { rejects } from 'node:assert/strict'

import { createProfileFixture, createSessionFixture } from '../../tests/fixtures'
import type { ResumeSessionRequest } from './contracts'
import { toScoutInput } from './profile-form'
import { createSessionClient, SessionHttpError } from './session-client'

const input = { ...toScoutInput(createProfileFixture()), request_id: 'create-1' }
const completed = createSessionFixture({
  session_id: 'session-1',
  outcome: 'completed',
  profile: null,
  clarification_questions: [],
  recommendation: {
    session_id: 'session-1',
    generated_at: '2026-10-03T00:00:00Z',
    jobs: [],
    warnings: [],
    introduction: '',
  },
  errors: [],
  warnings: [],
})

function createTransport(
  handler: (url: string, init: RequestInit) => Response | Promise<Response>,
) {
  return (url: string, init: RequestInit) => Promise.resolve(handler(url, init))
}

describe('Session HTTP API', () => {
  test('create/get/resume/delete use the backend paths and JSON contract', async () => {
    const requests: { url: string; init: RequestInit }[] = []
    const client = createSessionClient(
      '/api/v1/',
      createTransport((url, init) => {
        requests.push({ url, init })
        return init.method === 'DELETE'
          ? new Response(null, { status: 204 })
          : Response.json(completed, { status: init.method === 'POST' ? 202 : 200 })
      }),
    )
    const signal = new AbortController().signal
    expect(await client.start(input, signal)).toEqual(completed)
    expect(await client.get('session/1', signal)).toEqual(completed)
    const request: ResumeSessionRequest = {
      request_id: 'resume-1',
      expected_revision: 1,
      action: 'answer',
      message: 'Additional notes',
      answers: [
        { question_id: 'location-1', value: 'hk' },
        { question_id: 'directions-1', value: ['frontend', 'data'] },
      ],
      skipped_question_ids: ['optional-1'],
      profile_updates: { 'preferences.location': '香港' },
    }
    expect(await client.answer('session/1', request, signal)).toEqual(completed)
    await client.delete('session/1', signal)

    expect(requests.map(({ url, init }) => [url, init.method])).toEqual([
      ['/api/v1/sessions', 'POST'],
      ['/api/v1/sessions/session%2F1', 'GET'],
      ['/api/v1/sessions/session%2F1/resume', 'POST'],
      ['/api/v1/sessions/session%2F1', 'DELETE'],
    ])
    const startBody = requests[0]?.init.body
    const answerBody = requests[2]?.init.body
    if (typeof startBody !== 'string' || typeof answerBody !== 'string')
      throw new Error('Expected JSON request bodies')
    expect(JSON.parse(startBody)).toEqual(input)
    expect(JSON.parse(answerBody)).toEqual(request)
    expect(requests.every(({ init }) => init.signal === signal)).toBe(true)
    expect(requests[0]?.init.headers).toHaveProperty('Content-Type', 'application/json')
    expect(requests[1]?.init.body).toBeUndefined()
    expect(requests[3]?.init.body).toBeUndefined()
  })

  test('paused and failed workflow outcomes remain successful HTTP responses', async () => {
    for (const outcome of ['running', 'paused', 'failed'] as const) {
      const response = {
        ...completed,
        outcome,
        recommendation: null,
        warnings: ['Source search notice'],
      }
      const client = createSessionClient(
        '/api/v1',
        createTransport(() => Response.json(response)),
      )
      expect(await client.start(input)).toEqual(response)
    }
  })

  test('HTTP errors reject with status for recovery', async () => {
    for (const status of [404, 409, 422, 503]) {
      const client = createSessionClient(
        '/api/v1',
        createTransport(() => Response.json({ detail: 'Backend error' }, { status })),
      )
      await rejects(
        client.get('session-1'),
        (error: unknown) => error instanceof SessionHttpError && error.status === status,
      )
    }
    const client = createSessionClient(
      '/api/v1',
      createTransport(() => new Response('Bad gateway', { status: 502 })),
    )
    await rejects(client.get('session-1'), { status: 502 })
  })

  test('network failures and invalid responses reject', async () => {
    const offline = createSessionClient(
      '/api/v1',
      createTransport(() => {
        throw new TypeError('Failed to fetch')
      }),
    )
    await rejects(offline.start(input), Error)
    const invalidJson = createSessionClient(
      '/api/v1',
      createTransport(() => new Response('<html>Proxy misconfigured</html>')),
    )
    await rejects(invalidJson.get('session-1'), Error)
    const invalidSession = createSessionClient(
      '/api/v1',
      createTransport(() => Response.json({ session_id: 'session-1', outcome: 'running' })),
    )
    await rejects(invalidSession.get('session-1'), Error)
  })

  test('aborted requests preserve the abort error', async () => {
    const controller = new AbortController()
    controller.abort()
    const client = createSessionClient(
      '/api/v1',
      createTransport((_url, init) => {
        init.signal?.throwIfAborted()
        return Response.json(completed)
      }),
    )
    await rejects(
      client.get('session-1', controller.signal),
      (error: unknown) => error === controller.signal.reason,
    )
  })
})
