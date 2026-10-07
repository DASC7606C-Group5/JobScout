import { createApiClient, type ApiFetcher } from './api-client'
import { vResumeInput } from './api-schemas'
import { ApplicantRequestError, responseErrorCode } from './applicant-errors'
import { authenticatedFetch } from './auth-client'
import type { ScoutInput } from './contracts'

export const RESUME_FILE_ACCEPT =
  '.pdf,.docx,.txt,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain'
export const MAX_RESUME_BYTES = 10 * 1024 * 1024
export const MAX_RESUME_TEXT_LENGTH = 100_000

type ResumePayload = NonNullable<ScoutInput['resume']>

function validateText(text: string): string {
  const normalized = text
    .replace(/^\uFEFF/, '')
    .replace(/\r\n?/g, '\n')
    .trim()
  if (!normalized) throw new ApplicantRequestError('empty_text')
  if (normalized.includes('\u0000') || normalized.includes('\uFFFD'))
    throw new ApplicantRequestError('invalid_text')
  if (normalized.length > MAX_RESUME_TEXT_LENGTH) throw new ApplicantRequestError('text_too_long')
  return normalized
}

export function createResumeReader(baseUrl = '/api/v1', fetcher: ApiFetcher = authenticatedFetch) {
  const client = createApiClient(
    baseUrl,
    fetcher,
    (status, data) => new ApplicantRequestError(responseErrorCode(data, status)),
  )
  return async function readResume(file: File, signal?: AbortSignal): Promise<ResumePayload> {
    signal?.throwIfAborted()
    const extension = file.name.split('.').pop()?.toLowerCase()
    if (!/\.(txt|pdf|docx)$/i.test(file.name)) throw new ApplicantRequestError('unsupported_format')
    if (file.size > MAX_RESUME_BYTES) throw new ApplicantRequestError('file_too_large')
    if (!file.size) throw new ApplicantRequestError('empty_file')
    if (extension === 'txt') {
      const text = await file.text()
      signal?.throwIfAborted()
      return { name: file.name, text: validateText(text) }
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
    return { name: data.name, text: validateText(data.text) }
  }
}

export const readResume = createResumeReader(import.meta.env?.VITE_API_BASE_URL || '/api/v1')
