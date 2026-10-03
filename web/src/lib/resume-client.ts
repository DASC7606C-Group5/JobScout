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
  if (!normalized) throw new Error('这份文件没有文字，请检查后重新选择。')
  if (normalized.includes('\u0000') || normalized.includes('\uFFFD'))
    throw new Error('无法正确读取文字，请使用 UTF-8 TXT，或重新导出 PDF / DOCX 文档。')
  if (normalized.length > MAX_RESUME_TEXT_LENGTH)
    throw new Error('简历文字过多，请精简至 100,000 字以内。')
  return normalized
}

function parseErrorMessage(status: number, body: unknown): string {
  if (status >= 500) return '简历解析服务暂时不可用，请稍后重试。'
  if (body && typeof body === 'object' && 'detail' in body) {
    const detail = body.detail
    if (typeof detail === 'string') return detail
    if (detail && typeof detail === 'object' && 'message' in detail)
      if (typeof detail.message === 'string') return detail.message
  }
  if (status === 413) return '文件过大，请选择 10 MB 以内的简历。'
  return `简历解析未完成（HTTP ${status}），请检查文件后重试。`
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
      throw new Error('请上传 PDF、DOCX 或 UTF-8 TXT 简历。')
    if (file.size > MAX_RESUME_BYTES) throw new Error('文件过大，请选择 10 MB 以内的简历。')
    if (!file.size) throw new Error('这份文件为空，请检查后重新选择。')
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
      throw new Error('无法连接简历解析服务，请检查网络或稍后重试。')
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
      throw new Error('服务返回的简历格式不正确，请稍后重试。')
    return { name: data.name, text: validateText(data.text) }
  }
}

export const readResume = createResumeReader(import.meta.env?.VITE_API_BASE_URL || '/api/v1')
