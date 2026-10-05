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
  if (status === 404) return 'This session is no longer available. Start a new search.'
  if (status === 409) return 'The session has changed. Refresh it to see the latest results.'
  if (status === 422)
    return 'Some submitted information is invalid. Check your search criteria and try again.'
  if (status >= 500) return 'The service is temporarily unavailable. Try again later.'
  if (body && typeof body === 'object' && 'detail' in body && typeof body.detail === 'string')
    return body.detail
  return `Request failed (HTTP ${status}). Please try again.`
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
      throw new Error('Could not connect to the service. Check your network or try again later.')
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
      throw new Error('The service returned unreadable data. Try again later.')
    }
    if (
      !data ||
      typeof data.session_id !== 'string' ||
      !['running', 'paused', 'completed', 'failed'].includes(data.outcome) ||
      !Number.isInteger(data.revision) ||
      data.revision < 0 ||
      typeof data.current_stage !== 'string' ||
      !Array.isArray(data.conversation) ||
      !Array.isArray(data.source_outcomes) ||
      !['live', 'replay'].includes(data.mode) ||
      !Array.isArray(data.clarification_questions) ||
      !Array.isArray(data.errors) ||
      !Array.isArray(data.warnings)
    )
      throw new Error(
        'The service returned an invalid session response. Check your API configuration.',
      )
    return data
  }
  const pathFor = (id: string) => `/sessions/${encodeURIComponent(id)}`
  return {
    start: (input, signal) => session('/sessions', 'POST', input, signal),
    get: (id, signal) => session(pathFor(id), 'GET', undefined, signal),
    answer: (id, request, signal) => session(`${pathFor(id)}/resume`, 'POST', request, signal),
    delete: async (id, signal) => {
      await request(pathFor(id), 'DELETE', undefined, signal)
    },
  }
}

export const sessionClient = createSessionClient(import.meta.env?.VITE_API_BASE_URL || '/api/v1')
