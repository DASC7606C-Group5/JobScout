import { describe, expect, test } from 'bun:test'

import { createResumeReader, MAX_RESUME_BYTES, MAX_RESUME_TEXT_LENGTH } from './resume-client'

async function expectFailure(request: Promise<unknown>, message: string) {
  const error: unknown = await request.catch((cause: unknown) => cause)
  expect(error).toBeInstanceOf(Error)
  expect(error).toHaveProperty('message', expect.stringContaining(message))
}

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
    const read = createResumeReader('/api/v1', () => {
      throw new Error('Invalid files must not be uploaded')
    })
    const cases: [File, string][] = [
      [new File(['sample'], 'resume.doc'), 'PDF'],
      [new File(['sample'], 'pdf'), 'PDF'],
      [new File(['sample'], 'resume.rtf'), 'PDF'],
      [new File([], 'resume.pdf'), '文件为空'],
      [new File(['  '], 'resume.txt'), '没有文字'],
      [new File(['bad\u0000text'], 'resume.txt'), 'UTF-8'],
      [new File([new Uint8Array([0xff])], 'resume.txt'), 'UTF-8'],
      [new File([new Uint8Array(MAX_RESUME_BYTES + 1)], 'resume.pdf'), '10 MB'],
      [new File(['x'.repeat(MAX_RESUME_TEXT_LENGTH + 1)], 'resume.txt'), '100,000'],
    ]
    for (const [file, message] of cases) await expectFailure(read(file), message)
  })

  test('preserves useful parser errors and handles proxy and network failures', async () => {
    const file = new File(['sample'], 'resume.pdf')
    for (const [status, body, expected] of [
      [422, { detail: { code: 'no_extractable_text', message: '扫描件请先进行 OCR。' } }, 'OCR'],
      [415, { detail: '不支持这种文件格式。' }, '不支持'],
      [413, {}, '10 MB'],
      [503, { detail: 'internal diagnostics' }, '暂时不可用'],
    ] as const) {
      const read = createResumeReader('/api/v1', () =>
        Promise.resolve(Response.json(body, { status })),
      )
      await expectFailure(read(file), expected)
    }
    const proxyError = createResumeReader('/api/v1', () =>
      Promise.resolve(new Response('<html>Bad gateway</html>', { status: 502 })),
    )
    await expectFailure(proxyError(file), '暂时不可用')
    const offline = createResumeReader('/api/v1', () => Promise.reject(new TypeError('offline')))
    await expectFailure(offline(file), '无法连接')
  })

  test('rejects invalid successful responses', async () => {
    const file = new File(['sample'], 'resume.pdf')
    for (const body of [{ name: 'resume.pdf' }, { name: '', text: 'Python' }, null]) {
      const read = createResumeReader('/api/v1', () => Promise.resolve(Response.json(body)))
      await expectFailure(read(file), '简历格式不正确')
    }
    const invalidJson = createResumeReader('/api/v1', () =>
      Promise.resolve(new Response('<html>Not JSON</html>')),
    )
    await expectFailure(invalidJson(file), '简历格式不正确')
    const empty = createResumeReader('/api/v1', () =>
      Promise.resolve(Response.json({ name: file.name, text: ' ' })),
    )
    await expectFailure(empty(file), '没有文字')
  })

  test('passes cancellation to fetch and preserves abort errors', async () => {
    const controller = new AbortController()
    const read = createResumeReader('/api/v1', (_url, init) => {
      controller.abort()
      return Promise.reject(init.signal?.reason)
    })
    const error: unknown = await read(new File(['sample'], 'resume.pdf'), controller.signal).catch(
      (cause: unknown) => cause,
    )
    expect(error).toBe(controller.signal.reason)
    await expectFailure(read(new File(['sample'], 'resume.txt'), controller.signal), 'abort')
  })
})
