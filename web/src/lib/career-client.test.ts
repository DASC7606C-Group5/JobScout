import { expect, test } from 'bun:test'

import { createCareerClient } from './career-client'
import type { ProfileWrite } from './career-contracts'

test('feedback encodes stable IDs and preserves task-local intent', async () => {
  const calls: { url: string; body: unknown }[] = []
  const client = createCareerClient('/api/v1', async (url, init) => {
    calls.push({ url: url, body: JSON.parse(init.body as string) })
    return Response.json({ interest: 'not_interested', reason: '  Long commute\n', scope: 'task' })
  })
  await client.saveFeedback('task/1', 'source:jobs/42', {
    interest: 'not_interested',
    reason: '  Long commute\n',
    scope: 'task',
  })
  await client.saveFeedback('task/1', 'source:jobs/42', {
    interest: 'neutral',
    reason: '',
    scope: 'job',
  })
  expect(calls[0]).toEqual({
    url: '/api/v1/sessions/task%2F1/feedback/source%3Ajobs%2F42',
    body: { interest: 'not_interested', reason: '  Long commute\n', scope: 'task' },
  })
  expect(calls[1]?.body).toEqual({ interest: 'neutral', reason: '', scope: 'job' })
})

test('profile publication preserves normalized edits, raw material and evidence', async () => {
  const supplied: ProfileWrite = {
    expected_revision: 4,
    description: '  My background\n',
    resume: { name: 'CV.txt', text: 'Original\n' },
    background: { education: [], skills: ['SQL'], internships: [], projects: ['Reporting'] },
    documents: [
      {
        document_id: 'evidence:1',
        source: 'user',
        source_url: '',
        text: 'Evidence\n',
        fetched_at: '2026-10-07T00:00:00Z',
        is_excerpt: false,
      },
    ],
  }
  let sent: unknown
  const client = createCareerClient('/api/v1', async (_url, init) => {
    sent = JSON.parse(init.body as string)
    return Response.json({ ...supplied, revision: 5 })
  })
  const profile = await client.saveProfile(supplied)
  expect(sent).toEqual(supplied)
  expect(profile.revision).toBe(5)
  expect(profile.background.skills).toEqual(['SQL'])
})

test('application updates address global job IDs and reject failed writes', async () => {
  let path = ''
  const client = createCareerClient('/api/v1', async (url) => {
    path = url
    return Response.json({}, { status: 409 })
  })
  const rejected = await client
    .saveApplication('jobs/42', {
      stage: 'interview',
      note: 'Tuesday',
      session_id: 'task-a',
    })
    .then(
      () => null,
      (error: unknown) => error,
    )
  expect(rejected).toBeInstanceOf(Error)
  expect((rejected as Error).message).toContain('(409)')
  expect(path).toBe('/api/v1/applications/jobs%2F42')
})
