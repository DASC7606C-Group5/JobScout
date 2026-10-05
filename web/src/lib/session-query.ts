import { queryOptions } from '@tanstack/react-query'

import type { ScoutSession, SessionClient } from './contracts'
import { SessionHttpError } from './session-client'

export const sessionKey = (sessionId: string | null) => ['sessions', sessionId] as const

export function latestSessionSnapshot(confirmed: ScoutSession | undefined, incoming: ScoutSession) {
  if (!confirmed) return incoming
  if (confirmed.revision > incoming.revision) return confirmed
  if (
    confirmed.revision === incoming.revision &&
    confirmed.outcome !== 'running' &&
    incoming.outcome === 'running'
  )
    return confirmed
  return incoming
}

export function sessionQueryOptions(client: SessionClient, sessionId: string | null) {
  return queryOptions({
    queryKey: sessionKey(sessionId),
    queryFn: async ({ signal, client: cache }) => {
      if (!sessionId) throw new Error('No session has been created yet.')
      const incoming = await client.get(sessionId, signal)
      return latestSessionSnapshot(
        cache.getQueryData<ScoutSession>(sessionKey(sessionId)),
        incoming,
      )
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
