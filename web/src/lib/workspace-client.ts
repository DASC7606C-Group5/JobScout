import { createApiClient, type ApiFetcher } from './api-client'
import {
  vDraftResponse,
  vSessionHistoryResponse,
  vSavedJobsResponse,
  vRecommendationItem,
} from './api-schemas'
import { authenticatedFetch } from './auth-client'
import type { WorkspaceClient, SaveDraftRequest, DraftSection } from './contracts'

export const workspaceDraftPath = '/workspace/draft'
export const sessionDraftPath = (id: string, revision: number, section: string) =>
  `/sessions/${encodeURIComponent(id)}/drafts/${revision}/${section}`

export function createWorkspaceClient(
  baseUrl = '/api/v1',
  fetcher: ApiFetcher = authenticatedFetch,
): WorkspaceClient {
  const client = createApiClient(baseUrl, fetcher)
  const options = (signal?: AbortSignal) => (signal ? { signal } : {})
  function draft(path: string, body?: SaveDraftRequest, signal?: AbortSignal) {
    if (path === workspaceDraftPath)
      return body
        ? client.request(
            'put',
            '/api/v1/workspace/draft',
            { body, ...options(signal) },
            vDraftResponse,
          )
        : client.request('get', '/api/v1/workspace/draft', options(signal), vDraftResponse)
    const match = /^\/sessions\/([^/]+)\/drafts\/(\d+)\/(clarification|summary)$/.exec(path)
    if (!match) throw new Error('Invalid session draft path')
    const target = {
      session_id: decodeURIComponent(match[1]!),
      revision: Number(match[2]),
      section: match[3] as DraftSection,
    }
    return body
      ? client.request(
          'put',
          '/api/v1/sessions/{session_id}/drafts/{revision}/{section}',
          { path: target, body, ...options(signal) },
          vDraftResponse,
        )
      : client.request(
          'get',
          '/api/v1/sessions/{session_id}/drafts/{revision}/{section}',
          { path: target, ...options(signal) },
          vDraftResponse,
        )
  }
  return {
    history: (cursor, signal) =>
      client.request(
        'get',
        '/api/v1/sessions',
        { ...options(signal), query: { limit: 20, ...(cursor ? { cursor } : {}) } },
        vSessionHistoryResponse,
      ),
    getDraft: (path, signal) => draft(path, undefined, signal),
    saveDraft: (path, body) => draft(path, body),
    savedJobs: async (signal) =>
      (await client.request('get', '/api/v1/saved-jobs', options(signal), vSavedJobsResponse))
        .items,
    saveJob: (jobId, sessionId, revision) =>
      client.request(
        'put',
        '/api/v1/saved-jobs/{job_id}',
        { path: { job_id: jobId }, body: { session_id: sessionId, expected_revision: revision } },
        vRecommendationItem,
      ),
    removeJob: async (jobId) => {
      await client.request('delete', '/api/v1/saved-jobs/{job_id}', { path: { job_id: jobId } })
    },
  }
}
export const workspaceClient = createWorkspaceClient(
  import.meta.env?.VITE_API_BASE_URL || '/api/v1',
)
