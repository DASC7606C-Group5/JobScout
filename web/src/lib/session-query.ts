import { queryOptions } from '@tanstack/react-query'

import type { SessionClient } from './contracts'
import { SessionHttpError } from './session-client'

export const sessionKey = (sessionId: string | null) => ['sessions', sessionId] as const

export function sessionQueryOptions(client: SessionClient, sessionId: string | null) {
  return queryOptions({
    queryKey: sessionKey(sessionId),
    queryFn: ({ signal }) => {
      if (!sessionId) throw new Error('尚未创建会话。')
      return client.get(sessionId, signal)
    },
    enabled: sessionId !== null,
    staleTime: 30_000,
    networkMode: 'always',
    retry: (failureCount, error) =>
      !(error instanceof SessionHttpError && error.status < 500) && failureCount < 1,
  })
}
