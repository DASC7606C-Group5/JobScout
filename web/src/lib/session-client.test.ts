import { describe, expect, test } from 'bun:test'

import type { ScoutInput } from './contracts'
import { createDemoClient, readResume } from './session-client'

const client = createDemoClient(0)
const input: ScoutInput = {
  description: '熟悉 React 的应届毕业生',
  resume: null,
  target_directions: ['前端开发'],
  preferences: {
    location: '香港',
    location_unrestricted: false,
    employment_type: 'full-time',
    salary_range: null,
    work_mode: null,
    industry: null,
  },
}

describe('demo session integration', () => {
  test('complete input returns an overall five jobs without inventing profile skills', async () => {
    const session = await client.start(input, 'normal')
    expect(session.current_stage).toBe('completed')
    expect(session.recommendation?.jobs).toHaveLength(5)
    expect(new Set(session.recommendation?.jobs.map((item) => item.job.job_id)).size).toBe(5)
    expect(session.profile.skills).toEqual([])
    expect(session.recommendation?.jobs[0]?.job.freshness_status).toBe('unknown')
    expect(session.recommendation?.warnings.length).toBeGreaterThan(0)
  })

  test('missing preferences pause; partial answers cannot bypass clarification', async () => {
    const initial = await client.start(
      {
        ...input,
        target_directions: [],
        preferences: { ...input.preferences, location: null, employment_type: null },
      },
      'normal',
    )
    expect(initial.current_stage).toBe('clarify')
    expect(initial.clarification_questions).toHaveLength(3)
    const partial = await client.answer(
      initial,
      { target_directions: '前端开发，数据分析', 'preferences.location': '  ' },
      'normal',
    )
    expect(partial.current_stage).toBe('clarify')
    expect(partial.profile.missing_required_fields).toEqual([
      'preferences.location',
      'preferences.employment_type',
    ])
    const complete = await client.answer(
      partial,
      { 'preferences.location': '不限', 'preferences.employment_type': '全职' },
      'normal',
    )
    expect(complete.current_stage).toBe('completed')
    expect(complete.session_id).toBe(initial.session_id)
    expect(complete.profile.target_directions).toEqual(['前端开发', '数据分析'])
    expect(complete.profile.preferences.location_unrestricted).toBe(true)
    expect(complete.profile.preferences.location).toBeNull()
    expect(complete.profile.preferences.employment_type).toBe('full-time')
    expect(initial.profile.target_directions).toEqual([])
    expect(initial.clarification_questions.every((question) => question.status === 'pending')).toBe(
      true,
    )
  })

  test('separators alone are not a valid target direction', async () => {
    const initial = await client.start({ ...input, target_directions: [] }, 'normal')
    const next = await client.answer(initial, { target_directions: '，,、' }, 'normal')
    expect(next.current_stage).toBe('clarify')
    expect(next.profile.missing_required_fields).toContain('target_directions')
  })

  test('explicitly unrestricted location does not prompt for a city', async () => {
    const session = await client.start(
      {
        ...input,
        preferences: { ...input.preferences, location: null, location_unrestricted: true },
      },
      'normal',
    )
    expect(session.current_stage).toBe('completed')
  })

  test('forced clarification resumes with the answer and retains session identity', async () => {
    const initial = await client.start(input, 'clarify')
    const next = await client.answer(initial, { 'preferences.work_mode': '远程' }, 'clarify')
    expect(next.current_stage).toBe('completed')
    expect(next.profile.preferences.work_mode).toBe('remote')
    expect(next.recommendation?.session_id).toBe(initial.session_id)
  })

  test('empty search is a successful result, not an error', async () => {
    const session = await client.start(input, 'empty')
    expect(session.current_stage).toBe('completed')
    expect(session.recommendation?.jobs).toEqual([])
    expect(session.errors).toEqual([])
  })

  test('search failure can recover without losing preferences or changing session', async () => {
    const failed = await client.start(input, 'error')
    expect(failed.current_stage).toBe('failed')
    expect(failed.errors[0]?.code).toBe('SEARCH_UNAVAILABLE')
    const recovered = await client.retry(failed)
    expect(recovered.current_stage).toBe('completed')
    expect(recovered.errors).toEqual([])
    expect(recovered.profile.preferences).toEqual(input.preferences)
    expect(recovered.session_id).toBe(failed.session_id)
  })
})

describe('local resume input', () => {
  test('reads UTF-8 text without uploading it', async () => {
    expect(await readResume(new File([' React 开发经历 '], 'resume.TXT'))).toEqual({
      name: 'resume.TXT',
      text: 'React 开发经历',
    })
  })

  test('rejects unsupported, empty, binary and oversized files', async () => {
    const cases: [File, string][] = [
      [new File(['sample'], 'resume.pdf'), 'TXT'],
      [new File(['  '], 'resume.txt'), '没有文字'],
      [new File(['bad\u0000text'], 'resume.txt'), 'UTF-8'],
      [new File([new Uint8Array(1024 * 1024 + 1)], 'resume.txt'), '1 MB'],
    ]
    for (const [file, message] of cases) {
      const error: unknown = await readResume(file).catch((cause: unknown) => cause)
      expect(error).toBeInstanceOf(Error)
      expect(error).toHaveProperty('message', expect.stringContaining(message))
    }
  })
})
