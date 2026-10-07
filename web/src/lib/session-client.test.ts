import { describe, expect, test } from 'bun:test'
import { rejects } from 'node:assert/strict'

import {
  createProfileFixture,
  createRecommendationFixture,
  createSessionFixture,
} from '../../tests/fixtures'
import { SessionHttpError } from './api-client'
import type { ResumeSessionRequest } from './contracts'
import { toScoutInput } from './profile-form'
import { createSessionClient } from './session-client'

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
    pending_jobs: [],
    notices: [],
    introduction: '',
  },
  errors: [],
  notices: [],
})

function createTransport(
  handler: (url: string, init: RequestInit) => Response | Promise<Response>,
) {
  return (url: string, init: RequestInit) => Promise.resolve(handler(url, init))
}

describe('Session HTTP API', () => {
  test('session operations preserve their request identities, run IDs and JSON contract', async () => {
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
    const stopRequest = { request_id: 'stop-1', expected_revision: 3, run_id: 'run-3' }
    expect(await client.stop('session/1', stopRequest, signal)).toEqual(completed)

    expect(requests.map(({ url, init }) => [url, init.method])).toEqual([
      ['/api/v1/sessions', 'POST'],
      ['/api/v1/sessions/session%2F1', 'GET'],
      ['/api/v1/sessions/session%2F1/resume', 'POST'],
      ['/api/v1/sessions/session%2F1', 'DELETE'],
      ['/api/v1/sessions/session%2F1/stop', 'POST'],
    ])
    const startBody = requests[0]?.init.body
    const answerBody = requests[2]?.init.body
    const stopBody = requests[4]?.init.body
    if (
      typeof startBody !== 'string' ||
      typeof answerBody !== 'string' ||
      typeof stopBody !== 'string'
    )
      throw new Error('Expected JSON request bodies')
    expect(JSON.parse(startBody)).toEqual(input)
    expect(JSON.parse(answerBody)).toEqual(request)
    expect(JSON.parse(stopBody)).toEqual(stopRequest)
    expect(requests.every(({ init }) => init.signal === signal)).toBe(true)
    expect(new Headers(requests[0]?.init.headers).get('Content-Type')).toBe('application/json')
    expect(requests[1]?.init.body).toBeUndefined()
    expect(requests[3]?.init.body).toBeUndefined()
  })

  test('paused and failed workflow outcomes remain successful HTTP responses', async () => {
    for (const outcome of ['running', 'paused', 'failed'] as const) {
      const response = {
        ...completed,
        outcome,
        recommendation: null,
        notices: [],
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

  test('public error codes preserve recovery without displaying private response details', async () => {
    const diagnostic =
      'private-detail: Record index 0 gen-private kept as None detail_limit Group 6'
    for (const [status, body, code] of [
      [
        409,
        { detail: { code: 'request_conflict', message: diagnostic, action: 'reload' } },
        'request_conflict',
      ],
      [400, { detail: diagnostic }, 'request_failed'],
      [422, { detail: { code: diagnostic, message: diagnostic, action: null } }, 'invalid_input'],
      [
        503,
        { detail: { code: 'service_unavailable', message: diagnostic, action: 'retry' } },
        'service_unavailable',
      ],
    ] as const) {
      const client = createSessionClient(
        '/api/v1',
        createTransport(() => Response.json(body, { status })),
      )
      await rejects(
        client.get('session-1'),
        (error: unknown) =>
          error instanceof SessionHttpError &&
          error.status === status &&
          error.code === code &&
          !error.message.includes(diagnostic),
      )
    }
  })

  test('network failures and invalid responses reject', async () => {
    const offline = createSessionClient(
      '/api/v1',
      createTransport(() => {
        throw new TypeError('Failed to fetch')
      }),
    )
    await rejects(offline.start(input), { code: 'connection_unavailable' })
    const invalidJson = createSessionClient(
      '/api/v1',
      createTransport(() => new Response('<html>Proxy misconfigured</html>')),
    )
    await rejects(invalidJson.get('session-1'), { code: 'invalid_response' })
    const invalidSession = createSessionClient(
      '/api/v1',
      createTransport(() => Response.json({ session_id: 'session-1', outcome: 'running' })),
    )
    await rejects(invalidSession.get('session-1'), { code: 'invalid_response' })
  })

  test('requires the current notice, analysis, conversation and error contract before rendering', async () => {
    const item = createRecommendationFixture()
    const recommendation = { ...completed.recommendation!, jobs: [item] }
    const current = { ...completed, recommendation }
    const message = current.conversation[0]!
    const reason = item.matching_reasons[0]!
    const quote = reason.job_source_quotes[0]!
    const activity = {
      sequence: 1,
      job_id: item.job.job_id,
      title: item.job.title,
      company: item.job.company,
      location: item.job.location,
      status: 'reviewing',
      review_issue: null,
      exclusion_reasons: [],
      unknown_conditions: [],
      recommendation_fit: 'unknown',
    }
    const invalidReplies = [
      { ...current, notices: undefined },
      { ...current, conversation: [{ ...message, responses: undefined }] },
      { ...current, recommendation: { ...recommendation, notices: undefined } },
      { ...current, recommendation: { ...recommendation, pending_jobs: undefined } },
      { ...current, progress: { ...current.progress, matched_count: -1 } },
      ...[
        undefined,
        [{ ...activity, status: 'invented' }],
        [{ ...activity, sequence: 0 }],
        [{ ...activity, job_id: 42 }],
        [{ ...activity, recommendation_fit: 'excellent' }],
      ].map((activity) => ({ ...current, progress: { ...current.progress, activity } })),
      ...[undefined, -1, 1.5].map((discovered_count) => ({
        ...current,
        progress: { ...current.progress, discovered_count },
      })),
      { ...current, stop_reason: 'unknown_stop_reason' },
      { ...current, run_id: 42 },
      { ...current, profile: { ...current.profile, search_options: { result_count: 21 } } },
      {
        ...current,
        recommendation: { ...recommendation, jobs: [{ ...item, notices: undefined }] },
      },
      {
        ...current,
        recommendation: { ...recommendation, jobs: [{ ...item, analysis_status: undefined }] },
      },
      {
        ...current,
        recommendation: { ...recommendation, jobs: [{ ...item, analysis_status: 'fallback' }] },
      },
      ...[
        { code: 'private_provider_message', stage: 'matching' },
        { code: 'timeout', stage: 'private_stage' },
      ].map((review_issue) => ({
        ...current,
        recommendation: { ...recommendation, jobs: [{ ...item, review_issue }] },
      })),
      ...[
        { ...reason, job_source_quotes: undefined },
        { ...reason, profile_source_quotes: undefined },
        { ...reason, level: 'unsupported' },
        { ...reason, job_source_quotes: [{ ...quote, document_id: undefined }] },
        { ...reason, job_source_quotes: [{ ...quote, excerpt: 42 }] },
        { ...reason, job_source_quotes: [{ ...quote, source_url: 42 }] },
      ].map((matchingReason) => ({
        ...current,
        recommendation: {
          ...recommendation,
          jobs: [{ ...item, matching_reasons: [matchingReason] }],
        },
      })),
      { ...current, errors: [{ code: 'service_unavailable', message: 'Private failure' }] },
      {
        ...current,
        notices: [
          {
            code: 'listing_incomplete',
            scope: 'job',
            message: 'Listing notice',
            action: 'open_listing',
          },
        ],
      },
    ]
    for (const reply of invalidReplies) {
      const client = createSessionClient(
        '/api/v1',
        createTransport(() => Response.json(reply)),
      )
      await rejects(client.get('session-1'), { code: 'invalid_response' })
    }

    current.conversation = [
      {
        ...message,
        text: "User text: target_directions: ['React']; preferences.location: None",
        responses: [{ label: 'Supplied label', value: ['Original value'], status: 'answered' }],
      },
    ]
    current.progress = {
      ...current.progress,
      activity: [
        {
          ...activity,
          status: 'reviewing',
          review_issue: null,
          exclusion_reasons: [],
          unknown_conditions: [],
          recommendation_fit: 'unknown',
        },
      ],
    }
    const client = createSessionClient(
      '/api/v1',
      createTransport(() => Response.json(current)),
    )
    expect(await client.get('session-1')).toEqual(current)
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
