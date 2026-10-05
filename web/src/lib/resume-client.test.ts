import { describe, expect, test } from 'bun:test'
import { rejects } from 'node:assert/strict'

import { ApplicantRequestError } from './applicant-errors'
import { createResumeReader, MAX_RESUME_BYTES, MAX_RESUME_TEXT_LENGTH } from './resume-client'

describe('resume file input', () => {
  test('reads TXT locally and normalizes BOM and line endings', async () => {
    const read = createResumeReader('/api/v1', () => {
      throw new Error('TXT must not be uploaded')
    })
    expect(await read(new File(['\uFEFF React 开发经历\r\nPython '], 'resume.TXT'))).toEqual({
      name: 'resume.TXT',
      text: 'React 开发经历\nPython',
    })
  })

  test('uploads PDF and Word using multipart with the configured API prefix', async () => {
    for (const name of ['resume.PDF', '简历.pdf', '简历.DOCX']) {
      const file = new File(['sample fixture'], name)
      const controller = new AbortController()
      let calls = 0
      const read = createResumeReader('https://api.example.test/api/v1/', async (url, init) => {
        calls += 1
        expect(url).toBe('https://api.example.test/api/v1/resumes/parse')
        expect(init.method).toBe('POST')
        expect(init.headers).toEqual({ Accept: 'application/json' })
        expect(init.signal).toBe(controller.signal)
        if (!(init.body instanceof FormData)) throw new Error('Expected multipart form data')
        const uploaded = init.body.get('file')
        if (!(uploaded instanceof File)) throw new Error('Expected a file')
        expect(uploaded.name).toBe(name)
        expect(await uploaded.text()).toBe('sample fixture')
        return Response.json({ name, text: ' 技能\nPython, SQL ' })
      })
      expect(await read(file, controller.signal)).toEqual({ name, text: '技能\nPython, SQL' })
      expect(calls).toBe(1)
    }
  })

  test('rejects unsupported, empty, binary and oversized files before uploading', async () => {
    let uploads = 0
    const read = createResumeReader('/api/v1', () => {
      uploads += 1
      return Promise.resolve(Response.json({ name: 'resume.pdf', text: 'Parsed content' }))
    })
    const cases = [
      new File(['sample'], 'resume.doc'),
      new File(['sample'], 'pdf'),
      new File(['sample'], 'resume.rtf'),
      new File([], 'resume.pdf'),
      new File(['  '], 'resume.txt'),
      new File(['bad\u0000text'], 'resume.txt'),
      new File([new Uint8Array([0xff])], 'resume.txt'),
      new File([new Uint8Array(MAX_RESUME_BYTES + 1)], 'resume.pdf'),
      new File(['x'.repeat(MAX_RESUME_TEXT_LENGTH + 1)], 'resume.txt'),
    ]
    for (const file of cases) await rejects(read(file), Error)
    expect(uploads).toBe(0)
  })

  test('preserves parser recovery codes without disclosing diagnostic bodies', async () => {
    const file = new File(['sample'], 'resume.pdf')
    const parserMessage = 'parser-detail-sentinel'
    for (const [status, body, code] of [
      [
        422,
        {
          detail: {
            code: 'no_extractable_text',
            message: parserMessage,
            action: 'edit_conditions',
          },
        },
        'no_extractable_text',
      ],
      [415, { detail: parserMessage }, 'unsupported_format'],
      [
        400,
        { detail: { code: parserMessage, message: parserMessage, action: null } },
        'request_failed',
      ],
    ] as const) {
      const read = createResumeReader('/api/v1', () =>
        Promise.resolve(Response.json(body, { status })),
      )
      await rejects(
        read(file),
        (error: unknown) =>
          error instanceof ApplicantRequestError &&
          error.code === code &&
          !error.message.includes(parserMessage),
      )
    }
    for (const status of [500, 503]) {
      const diagnostic = 'private-server-diagnostic'
      const read = createResumeReader('/api/v1', () =>
        Promise.resolve(Response.json({ detail: diagnostic }, { status })),
      )
      await rejects(
        read(file),
        (error: unknown) => error instanceof Error && !error.message.includes(diagnostic),
      )
    }
    const oversized = createResumeReader('/api/v1', () =>
      Promise.resolve(Response.json({}, { status: 413 })),
    )
    await rejects(oversized(file), Error)
    const proxyError = createResumeReader('/api/v1', () =>
      Promise.resolve(new Response('<html>Bad gateway</html>', { status: 502 })),
    )
    await rejects(proxyError(file), Error)
    const offline = createResumeReader('/api/v1', () => Promise.reject(new TypeError('offline')))
    await rejects(offline(file), Error)
  })

  test('rejects invalid successful responses', async () => {
    const file = new File(['sample'], 'resume.pdf')
    for (const body of [{ name: 'resume.pdf' }, { name: '', text: 'Python' }, null]) {
      const read = createResumeReader('/api/v1', () => Promise.resolve(Response.json(body)))
      await rejects(read(file), Error)
    }
    const invalidJson = createResumeReader('/api/v1', () =>
      Promise.resolve(new Response('<html>Not JSON</html>')),
    )
    await rejects(invalidJson(file), Error)
    const empty = createResumeReader('/api/v1', () =>
      Promise.resolve(Response.json({ name: file.name, text: ' ' })),
    )
    await rejects(empty(file), Error)
  })

  test('passes cancellation to fetch and preserves abort errors', async () => {
    const controller = new AbortController()
    const read = createResumeReader('/api/v1', (_url, init) => {
      controller.abort()
      return Promise.reject(init.signal?.reason)
    })
    await rejects(
      read(new File(['sample'], 'resume.pdf'), controller.signal),
      (error: unknown) => error === controller.signal.reason,
    )
    await rejects(
      read(new File(['sample'], 'resume.txt'), controller.signal),
      (error: unknown) => error === controller.signal.reason,
    )
  })
})
