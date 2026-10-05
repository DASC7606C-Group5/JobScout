import { ApplicantRequestError, responseErrorCode } from './applicant-errors'
import type { DraftResponse, SessionHistory, WorkspaceClient } from './contracts'
import { SessionHttpError } from './session-client'
import { isRecommendationItem } from './session-response'

export const workspaceDraftPath = '/workspace/draft'
export const sessionDraftPath = (id: string, revision: number, section: string) =>
  `/sessions/${encodeURIComponent(id)}/drafts/${revision}/${section}`

function record(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value))
}

export function createWorkspaceClient(
  baseUrl = '/api/v1',
  fetcher: (url: string, init: RequestInit) => Promise<Response> = fetch,
): WorkspaceClient {
  const base = baseUrl.replace(/\/+$/, '')
  async function request(path: string, method: string, body?: unknown, signal?: AbortSignal) {
    let response: Response
    try {
      response = await fetcher(`${base}${path}`, {
        method,
        headers: {
          Accept: 'application/json',
          ...(body ? { 'Content-Type': 'application/json' } : {}),
        },
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
        ...(signal ? { signal } : {}),
      })
    } catch (error) {
      if (signal?.aborted) throw error
      throw new ApplicantRequestError('connection_unavailable')
    }
    if (!response.ok) {
      const error: unknown = await response.json().catch(() => null)
      throw new SessionHttpError(response.status, responseErrorCode(error, response.status))
    }
    return response
  }
  async function json(
    path: string,
    method: string,
    body?: unknown,
    signal?: AbortSignal,
  ): Promise<unknown> {
    const response = await request(path, method, body, signal)
    try {
      return await response.json()
    } catch {
      throw new ApplicantRequestError('invalid_response')
    }
  }
  async function draft(
    path: string,
    method: string,
    body?: unknown,
    signal?: AbortSignal,
  ): Promise<DraftResponse> {
    const data = await json(path, method, body, signal)
    if (
      !record(data) ||
      !record(data.data) ||
      !Number.isInteger(data.revision) ||
      typeof data.revision !== 'number' ||
      data.revision < 0 ||
      !(data.updated_at === null || typeof data.updated_at === 'string')
    )
      throw new ApplicantRequestError('invalid_response')
    return { data: data.data, revision: data.revision, updated_at: data.updated_at }
  }
  return {
    history: async (cursor, signal) => {
      const params = new URLSearchParams({ limit: '20' })
      if (cursor) params.set('cursor', cursor)
      const data = await json(`/sessions?${params}`, 'GET', undefined, signal)
      if (
        !record(data) ||
        !Array.isArray(data.items) ||
        !(data.next_cursor === null || typeof data.next_cursor === 'string') ||
        !data.items.every(
          (item) =>
            record(item) &&
            typeof item.session_id === 'string' &&
            typeof item.title === 'string' &&
            typeof item.location === 'string' &&
            typeof item.created_at === 'string' &&
            typeof item.updated_at === 'string' &&
            ['running', 'paused', 'completed', 'failed'].includes(String(item.outcome)) &&
            typeof item.current_stage === 'string' &&
            Number.isInteger(item.revision) &&
            typeof item.retryable === 'boolean' &&
            ['live', 'replay'].includes(String(item.mode)),
        )
      )
        throw new ApplicantRequestError('invalid_response')
      return data as unknown as SessionHistory
    },
    getDraft: (path, signal) => draft(path, 'GET', undefined, signal),
    saveDraft: (path, body) => draft(path, 'PUT', body),
    savedJobs: async (signal) => {
      const data = await json('/saved-jobs', 'GET', undefined, signal)
      if (!record(data) || !Array.isArray(data.items) || !data.items.every(isRecommendationItem))
        throw new ApplicantRequestError('invalid_response')
      return data.items
    },
    saveJob: async (jobId, sessionId, revision) => {
      const data = await json(`/saved-jobs/${encodeURIComponent(jobId)}`, 'PUT', {
        session_id: sessionId,
        expected_revision: revision,
      })
      if (!isRecommendationItem(data)) throw new ApplicantRequestError('invalid_response')
      return data
    },
    removeJob: async (jobId) => {
      await request(`/saved-jobs/${encodeURIComponent(jobId)}`, 'DELETE')
    },
  }
}

export const workspaceClient = createWorkspaceClient(
  import.meta.env?.VITE_API_BASE_URL || '/api/v1',
)
