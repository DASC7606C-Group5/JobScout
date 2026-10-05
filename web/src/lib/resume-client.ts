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
  if (!normalized) throw new Error('This file contains no text. Check it and try again.')
  if (normalized.includes('\u0000') || normalized.includes('\uFFFD'))
    throw new Error(
      'The text could not be read correctly. Use a UTF-8 TXT file or re-export the PDF or DOCX document.',
    )
  if (normalized.length > MAX_RESUME_TEXT_LENGTH)
    throw new Error('The resume is too long. Shorten it to 100,000 characters or fewer.')
  return normalized
}

function parseErrorMessage(status: number, body: unknown): string {
  if (status >= 500)
    return 'The resume parsing service is temporarily unavailable. Try again later.'
  if (body && typeof body === 'object' && 'detail' in body) {
    const detail = body.detail
    if (typeof detail === 'string') return detail
    if (detail && typeof detail === 'object' && 'message' in detail)
      if (typeof detail.message === 'string') return detail.message
  }
  if (status === 413) return 'The file is too large. Choose a resume under 10 MB.'
  return `Resume parsing failed (HTTP ${status}). Check the file and try again.`
}

export function createResumeReader(
  baseUrl = '/api/v1',
  fetcher: (url: string, init: RequestInit) => Promise<Response> = fetch,
) {
  const base = baseUrl.replace(/\/+$/, '')
  return async function readResume(file: File, signal?: AbortSignal): Promise<ResumePayload> {
    signal?.throwIfAborted()
    const extension = file.name.split('.').pop()?.toLowerCase()
    if (!/\.(txt|pdf|docx)$/i.test(file.name))
      throw new Error('Upload your resume as a PDF, DOCX, or UTF-8 TXT file.')
    if (file.size > MAX_RESUME_BYTES)
      throw new Error('The file is too large. Choose a resume under 10 MB.')
    if (!file.size) throw new Error('This file is empty. Check it and try again.')
    if (extension === 'txt') {
      const text = await file.text()
      signal?.throwIfAborted()
      return { name: file.name, text: validateText(text) }
    }
    const form = new FormData()
    form.append('file', file)
    let response: Response
    try {
      response = await fetcher(`${base}/resumes/parse`, {
        method: 'POST',
        headers: { Accept: 'application/json' },
        body: form,
        ...(signal ? { signal } : {}),
      })
    } catch (error) {
      if (signal?.aborted) throw error
      throw new Error(
        'Could not connect to the resume parsing service. Check your network or try again later.',
      )
    }
    signal?.throwIfAborted()
    const data: unknown = await response.json().catch(() => null)
    if (!response.ok) throw new Error(parseErrorMessage(response.status, data))
    if (
      !data ||
      typeof data !== 'object' ||
      !('name' in data) ||
      typeof data.name !== 'string' ||
      !data.name.trim() ||
      !('text' in data) ||
      typeof data.text !== 'string'
    )
      throw new Error('The service returned an invalid resume format. Try again later.')
    return { name: data.name, text: validateText(data.text) }
  }
}

export const readResume = createResumeReader(import.meta.env?.VITE_API_BASE_URL || '/api/v1')
