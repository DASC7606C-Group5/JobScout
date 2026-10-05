import { queryOptions } from '@tanstack/react-query'

import type { SessionClient } from './contracts'
import { SessionHttpError } from './session-client'

export const sessionKey = (sessionId: string | null) => ['sessions', sessionId] as const

export function sessionQueryOptions(client: SessionClient, sessionId: string | null) {
  return queryOptions({
    queryKey: sessionKey(sessionId),
    queryFn: ({ signal }) => {
      if (!sessionId) throw new Error('No session has been created yet.')
      return client.get(sessionId, signal)
    },
    enabled: sessionId !== null,
    staleTime: 30_000,
    refetchInterval: (query) =>
      query.state.status !== 'error' && query.state.data?.outcome === 'running' ? 1000 : false,
    refetchIntervalInBackground: true,
    refetchOnWindowFocus: false,
    networkMode: 'always',
    retry: (failureCount, error) =>
      !(error instanceof SessionHttpError && error.status < 500) && failureCount < 1,
  })
}
