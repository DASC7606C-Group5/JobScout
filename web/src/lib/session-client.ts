import type { ScoutSession, SessionClient } from './contracts'

export class SessionHttpError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message)
    this.name = 'SessionHttpError'
  }
}

function errorMessage(status: number, body: unknown): string {
  if (status === 404) return '会话已不存在，请重新搜索。'
  if (status === 409) return '会话状态已更新，请刷新会话查看最新结果。'
  if (status === 422) return '提交的资料格式不正确，请检查求职条件后再试。'
  if (status >= 500) return '服务暂时不可用，请稍后重试。'
  if (body && typeof body === 'object' && 'detail' in body && typeof body.detail === 'string')
    return body.detail
  return `请求未完成（HTTP ${status}），请重试。`
}

export function createSessionClient(
  baseUrl = '/api/v1',
  fetcher: (url: string, init: RequestInit) => Promise<Response> = fetch,
): SessionClient {
  const base = baseUrl.replace(/\/+$/, '')
  async function request(path: string, method: string, body?: unknown, signal?: AbortSignal) {
    let response: Response
    try {
      response = await fetcher(`${base}${path}`, {
        method,
        headers:
          body === undefined
            ? { Accept: 'application/json' }
            : {
                Accept: 'application/json',
                'Content-Type': 'application/json',
              },
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
        ...(signal ? { signal } : {}),
      })
    } catch (error) {
      if (signal?.aborted) throw error
      throw new Error('无法连接服务，请检查网络或稍后重试。')
    }
    if (!response.ok) {
      const data: unknown = await response.json().catch(() => null)
      throw new SessionHttpError(response.status, errorMessage(response.status, data))
    }
    return response
  }
  async function session(path: string, method: string, body?: unknown, signal?: AbortSignal) {
    const response = await request(path, method, body, signal)
    let data: ScoutSession
    try {
      data = (await response.json()) as ScoutSession
    } catch {
      throw new Error('服务返回了无法读取的数据，请稍后重试。')
    }
    if (
      !data ||
      typeof data.session_id !== 'string' ||
      !['paused', 'completed', 'failed'].includes(data.outcome) ||
      !Array.isArray(data.clarification_questions) ||
      !Array.isArray(data.errors) ||
      !Array.isArray(data.warnings)
    )
      throw new Error('服务返回的会话格式不正确，请检查 API 配置。')
    return data
  }
  const pathFor = (id: string) => `/sessions/${encodeURIComponent(id)}`
  return {
    start: (input, signal) => session('/sessions', 'POST', input, signal),
    get: (id, signal) => session(pathFor(id), 'GET', undefined, signal),
    answer: (id, answers, signal) => session(`${pathFor(id)}/resume`, 'POST', { answers }, signal),
    delete: async (id, signal) => {
      await request(pathFor(id), 'DELETE', undefined, signal)
    },
  }
}

export const sessionClient = createSessionClient(import.meta.env?.VITE_API_BASE_URL || '/api/v1')
