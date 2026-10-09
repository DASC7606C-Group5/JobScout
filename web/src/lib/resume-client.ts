import type { ResumeLimits } from '../api/types.gen'
import { createApiClient, type ApiFetcher } from './api-client'
import { vResumeInput, vResumeLimits } from './api-schemas'
import { ApplicantRequestError, responseErrorCode } from './applicant-errors'
import { authenticatedFetch, identityEvents } from './auth-client'
import type { ScoutInput } from './contracts'

export const RESUME_FILE_ACCEPT =
  '.pdf,.docx,.txt,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain'

type ResumePayload = NonNullable<ScoutInput['resume']>

function waitForUploadSlot(milliseconds: number, signal?: AbortSignal | null): Promise<void> {
  signal?.throwIfAborted()
  return new Promise((resolve, reject) => {
    const finish = () => {
      clearTimeout(timer)
      signal?.removeEventListener('abort', abort)
    }
    const abort = () => {
      finish()
      reject(signal?.reason ?? new DOMException('Upload cancelled', 'AbortError'))
    }
    const timer = setTimeout(() => {
      finish()
      resolve()
    }, milliseconds)
    signal?.addEventListener('abort', abort, { once: true })
  })
}

function retryBusyUpload(fetcher: ApiFetcher): ApiFetcher {
  return async (url, init) => {
    const accountChange = new AbortController()
    const signal = init.signal
      ? AbortSignal.any([init.signal, accountChange.signal])
      : accountChange.signal
    const abort = () => accountChange.abort()
    identityEvents.addEventListener('change', abort, { once: true })
    const deadline = Date.now() + 90_000
    try {
      for (let retries = 0; ; retries += 1) {
        signal.throwIfAborted()
        const response = await fetcher(url, init)
        signal.throwIfAborted()
        if (init.method !== 'POST' || response.status !== 429 || retries >= 8) return response
        const body: unknown = await response
          .clone()
          .json()
          .catch(() => null)
        if (responseErrorCode(body, response.status) !== 'upload_capacity') return response
        const retryAfter = response.headers.get('Retry-After')
        const seconds = retryAfter === null ? Number.NaN : Number(retryAfter)
        const date = retryAfter === null ? Number.NaN : Date.parse(retryAfter)
        const minimum =
          Number.isFinite(seconds) && seconds >= 0
            ? seconds * 1000
            : Number.isFinite(date)
              ? Math.max(0, date - Date.now())
              : 10_000
        const delay = minimum + Math.random() * 2000
        if (Date.now() + delay >= deadline) return response
        await response.body?.cancel()
        await waitForUploadSlot(delay, signal)
      }
    } finally {
      identityEvents.removeEventListener('change', abort)
    }
  }
}

function validateText(text: string, limits: ResumeLimits): string {
  const normalized = text
    .replace(/^\uFEFF/, '')
    .replace(/\r\n?/g, '\n')
    .trim()
  if (!normalized) throw new ApplicantRequestError('empty_text')
  if (normalized.includes('\u0000') || normalized.includes('\uFFFD'))
    throw new ApplicantRequestError('invalid_text')
  if (Array.from(normalized).length > limits.max_text_characters)
    throw new ApplicantRequestError('text_too_long')
  return normalized
}

export function createResumeReader(baseUrl = '/api/v1', fetcher: ApiFetcher = authenticatedFetch) {
  const client = createApiClient(
    baseUrl,
    retryBusyUpload(fetcher),
    (status, data) => new ApplicantRequestError(responseErrorCode(data, status)),
  )
  return async function readResume(file: File, signal?: AbortSignal): Promise<ResumePayload> {
    signal?.throwIfAborted()
    const extension = file.name.split('.').pop()?.toLowerCase()
    if (!/\.(txt|pdf|docx)$/i.test(file.name)) throw new ApplicantRequestError('unsupported_format')
    const limits = await client.request(
      'get',
      '/api/v1/resumes/limits',
      signal ? { signal } : {},
      vResumeLimits,
    )
    if (file.size > limits.max_bytes) throw new ApplicantRequestError('file_too_large')
    if (!file.size) throw new ApplicantRequestError('empty_file')
    if (extension === 'txt') {
      const text = await file.text()
      signal?.throwIfAborted()
      return { name: file.name, text: validateText(text, limits) }
    }
    const form = new FormData()
    form.append('file', file)
    const data = await client.request(
      'post',
      '/api/v1/resumes/parse',
      { body: form, ...(signal ? { signal } : {}) },
      vResumeInput,
    )
    signal?.throwIfAborted()
    if (!data.name.trim()) throw new ApplicantRequestError('invalid_response')
    return { name: data.name, text: validateText(data.text, limits) }
  }
}

export const readResume = createResumeReader(import.meta.env?.VITE_API_BASE_URL || '/api/v1')

export function readResumeLimits(signal?: AbortSignal) {
  return createApiClient(
    import.meta.env?.VITE_API_BASE_URL || '/api/v1',
    authenticatedFetch,
  ).request('get', '/api/v1/resumes/limits', signal ? { signal } : {}, vResumeLimits)
}
