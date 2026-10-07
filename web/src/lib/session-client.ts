import {
  applicantErrorAction,
  applicantErrorMessage,
  ApplicantRequestError,
  responseErrorCode,
  type ApplicantErrorCode,
} from './applicant-errors'
import type { SessionClient } from './contracts'
import { subscribeToSession } from './session-events'
import { isSessionResponse } from './session-response'

export class SessionHttpError extends Error {
  constructor(
    public status: number,
    public code: ApplicantErrorCode,
  ) {
    super(applicantErrorMessage(code, status))
    this.name = 'SessionHttpError'
  }
  get action() {
    return applicantErrorAction(this.code, this.status)
  }
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
      throw new ApplicantRequestError('connection_unavailable')
    }
    if (!response.ok) {
      const data: unknown = await response.json().catch(() => null)
      const code = responseErrorCode(data, response.status)
      throw new SessionHttpError(response.status, code)
    }
    return response
  }
  async function session(path: string, method: string, body?: unknown, signal?: AbortSignal) {
    const response = await request(path, method, body, signal)
    let data: unknown
    try {
      data = await response.json()
    } catch {
      throw new ApplicantRequestError('invalid_response')
    }
    if (!isSessionResponse(data)) throw new ApplicantRequestError('invalid_response')
    return data
  }
  const pathFor = (id: string) => `/sessions/${encodeURIComponent(id)}`
  return {
    start: (input, signal) => session('/sessions', 'POST', input, signal),
    get: (id, signal) => session(pathFor(id), 'GET', undefined, signal),
    subscribe: (id, handlers) => subscribeToSession(`${base}${pathFor(id)}/events`, id, handlers),
    answer: (id, request, signal) => session(`${pathFor(id)}/resume`, 'POST', request, signal),
    stop: (id, request, signal) => session(`${pathFor(id)}/stop`, 'POST', request, signal),
    delete: async (id, signal) => {
      await request(pathFor(id), 'DELETE', undefined, signal)
    },
  }
}

export const sessionClient = createSessionClient(import.meta.env?.VITE_API_BASE_URL || '/api/v1')
