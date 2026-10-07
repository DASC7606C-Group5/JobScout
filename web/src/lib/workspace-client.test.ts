import { describe, expect, test } from 'bun:test'
import { rejects } from 'node:assert/strict'

import {
  createMatchScoreFixture,
  createProfileFixture,
  createRecommendationFixture,
} from '../../tests/fixtures'
import type { SessionSummary } from './contracts'
import { createWorkspaceClient, sessionDraftPath } from './workspace-client'

function jsonBody(body: BodyInit | null | undefined): unknown {
  if (typeof body !== 'string') throw new Error('Expected a JSON request body')
  return JSON.parse(body)
}

describe('persistent shared workspace API', () => {
  test('draft saves retain raw form values with request identity and independent version', async () => {
    const supplied = {
      ...createProfileFixture(),
      description: '  原文  ',
      directions: '前端， 数据分析，',
    }
    const calls: { url: string; init: RequestInit }[] = []
    const client = createWorkspaceClient('/api/v1/', (url, init) => {
      calls.push({ url, init })
      return Promise.resolve(
        Response.json({ data: supplied, revision: 3, updated_at: '2026-10-06T00:00:00Z' }),
      )
    })
    const request = { data: supplied, request_id: 'draft-1', expected_revision: 2 }
    expect((await client.saveDraft('/workspace/draft', request)).data).toEqual(supplied)
    expect(calls[0]?.url).toBe('/api/v1/workspace/draft')
    expect(jsonBody(calls[0]?.init.body)).toEqual(request)
    await client.getDraft(sessionDraftPath('search/1', 4, 'clarification'))
    expect(calls[1]?.url).toBe('/api/v1/sessions/search%2F1/drafts/4/clarification')
  })

  test('history paging preserves stable session IDs and supplied summary fields', async () => {
    const summary: SessionSummary = {
      session_id: 'search-1',
      title: '前端开发',
      location: '香港',
      created_at: '2026-10-05T00:00:00Z',
      updated_at: '2026-10-06T00:00:00Z',
      outcome: 'paused',
      current_stage: 'confirmation',
      revision: 2,
      retryable: false,
      mode: 'live',
    }
    let requested = ''
    const client = createWorkspaceClient('/api/v1', (url) => {
      requested = url
      return Promise.resolve(Response.json({ items: [summary], next_cursor: 'next/2' }))
    })
    expect(await client.history('previous/1')).toEqual({ items: [summary], next_cursor: 'next/2' })
    expect(requested).toBe('/api/v1/sessions?limit=20&cursor=previous%2F1')
  })

  test('saved job writes reference the source version and return independent recommendation snapshots', async () => {
    const item = createRecommendationFixture()
    const calls: { url: string; init: RequestInit }[] = []
    const client = createWorkspaceClient('/api/v1', (url, init) => {
      calls.push({ url, init })
      return Promise.resolve(
        init.method === 'DELETE'
          ? new Response(null, { status: 204 })
          : Response.json(init.method === 'GET' ? { items: [item] } : item),
      )
    })
    expect(await client.savedJobs()).toEqual([item])
    expect(await client.saveJob('job/1', 'search-1', 7)).toEqual(item)
    expect(calls[1]?.url).toBe('/api/v1/saved-jobs/job%2F1')
    expect(jsonBody(calls[1]?.init.body)).toEqual({
      session_id: 'search-1',
      expected_revision: 7,
    })
    await client.removeJob('job/1')
    expect(calls[2]?.init.method).toBe('DELETE')
  })

  test('stale draft responses reject with the conflict identity without leaking private diagnostics', async () => {
    const client = createWorkspaceClient('/api/v1', () =>
      Promise.resolve(
        Response.json(
          { detail: { code: 'draft_conflict', message: 'Private database detail' } },
          { status: 409 },
        ),
      ),
    )
    await rejects(
      client.saveDraft('/workspace/draft', {
        data: {},
        request_id: 'conflict-1',
        expected_revision: 1,
      }),
      (error: unknown) =>
        error instanceof Error &&
        'code' in error &&
        error.code === 'draft_conflict' &&
        !error.message.includes('Private database detail'),
    )
  })

  test('malformed successful workspace contracts reject before use by the UI', async () => {
    const invalidDraft = createWorkspaceClient('/api/v1', () =>
      Promise.resolve(Response.json({ data: {}, revision: -1, updated_at: null })),
    )
    await rejects(invalidDraft.getDraft('/workspace/draft'), { code: 'invalid_response' })
    const invalidSaved = createWorkspaceClient('/api/v1', () =>
      Promise.resolve(Response.json({ items: [{ job: { job_id: 'broken' } }] })),
    )
    await rejects(invalidSaved.savedJobs(), { code: 'invalid_response' })
    const invalidHistory = createWorkspaceClient('/api/v1', () =>
      Promise.resolve(Response.json({ items: [{ session_id: 'broken' }], next_cursor: null })),
    )
    await rejects(invalidHistory.history(null), { code: 'invalid_response' })
  })
})

test('saved snapshots reject missing or duplicate axes and numeric unknown scores', async () => {
  const score = createMatchScoreFixture()
  const first = score.dimensions[0]!
  const invalidScores = [
    { ...score, dimensions: score.dimensions.slice(1) },
    { ...score, dimensions: score.dimensions.map(() => first) },
    {
      ...score,
      dimensions: [{ ...first, status: 'unknown', score: 42 }, ...score.dimensions.slice(1)],
    },
  ]
  for (const match_score of invalidScores) {
    const item = { ...createRecommendationFixture(), match_score }
    const client = createWorkspaceClient('/api/v1', (_url, init) =>
      Promise.resolve(Response.json(init.method === 'GET' ? { items: [item] } : item)),
    )
    await rejects(client.savedJobs(), { code: 'invalid_response' })
    await rejects(client.saveJob(item.job.job_id, 'search-1', 7), { code: 'invalid_response' })
  }
})
