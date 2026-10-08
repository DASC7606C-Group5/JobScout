import { createApiClient, type ApiFetcher } from './api-client'
import { vSessionResponse } from './api-schemas'
import { authenticatedFetch } from './auth-client'
import type { SessionClient } from './contracts'
import { subscribeToSession } from './session-events'

export function createSessionClient(
  baseUrl = '/api/v1',
  fetcher: ApiFetcher = authenticatedFetch,
): SessionClient {
  const client = createApiClient(baseUrl, fetcher)
  const options = (signal?: AbortSignal) => (signal ? { signal } : {})
  return {
    start: (body, signal) =>
      client.request('post', '/api/v1/sessions', { ...options(signal), body }, vSessionResponse),
    get: (id, signal) =>
      client.request(
        'get',
        '/api/v1/sessions/{session_id}',
        { ...options(signal), path: { session_id: id } },
        vSessionResponse,
      ),
    subscribe: (id, handlers) =>
      subscribeToSession(
        `${baseUrl.replace(/\/+$/, '')}/sessions/${encodeURIComponent(id)}/events`,
        id,
        handlers,
      ),
    answer: (id, body, signal) =>
      client.request(
        'post',
        '/api/v1/sessions/{session_id}/resume',
        { ...options(signal), path: { session_id: id }, body },
        vSessionResponse,
      ),
    stop: (id, body, signal) =>
      client.request(
        'post',
        '/api/v1/sessions/{session_id}/stop',
        { ...options(signal), path: { session_id: id }, body },
        vSessionResponse,
      ),
    feedback: (id, body, signal) =>
      client.request(
        'post',
        '/api/v1/sessions/{session_id}/feedback',
        { ...options(signal), path: { session_id: id }, body },
        vSessionResponse,
      ),
    followUp: (id, body, signal) =>
      client.request(
        'post',
        '/api/v1/sessions/{session_id}/follow-up',
        { ...options(signal), path: { session_id: id }, body },
        vSessionResponse,
      ),
    delete: async (id, signal) => {
      await client.request('delete', '/api/v1/sessions/{session_id}', {
        ...options(signal),
        path: { session_id: id },
      })
    },
  }
}
export const sessionClient = createSessionClient(import.meta.env?.VITE_API_BASE_URL || '/api/v1')
