import { queryOptions } from '@tanstack/react-query'

import { SessionHttpError } from './api-client'
import type { ScoutSession, SessionClient } from './contracts'

export const sessionKey = (sessionId: string | null) => ['sessions', sessionId] as const

export function latestSessionSnapshot(confirmed: ScoutSession | undefined, incoming: ScoutSession) {
  if (!confirmed) return incoming
  if (confirmed.snapshot_version > incoming.snapshot_version) return confirmed

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
    refetchOnWindowFocus: false,
    networkMode: 'always',
    retry: (failureCount, error) =>
      !(error instanceof SessionHttpError && error.status < 500) && failureCount < 1,
  })
}
