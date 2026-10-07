import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'

import { SessionHttpError } from '../lib/api-client'
import { ApplicantRequestError } from '../lib/applicant-errors'
import type { ScoutSession, SessionClient } from '../lib/contracts'
import { latestSessionSnapshot, sessionKey, sessionQueryOptions } from '../lib/session-query'

export function useSessionStream(
  client: SessionClient,
  session: ScoutSession | null,
  suspended: boolean,
  queryError: Error | null,
) {
  const cache = useQueryClient()
  const sessionId = session?.session_id
  const enabled =
    session?.outcome === 'running' &&
    !suspended &&
    !(queryError instanceof SessionHttpError && queryError.status < 500)
  const [attempt, setAttempt] = useState(0)
  const scope = `${sessionId}:${session?.revision}:${attempt}`
  const [failure, setFailure] = useState<{ scope: string; error: Error } | null>(null)
  useEffect(() => {
    if (!sessionId || !enabled) return
    let active = true
    const close = client.subscribe(sessionId, {
      onSnapshot: (incoming) => {
        if (!active) return
        setFailure(null)
        cache.setQueryData<ScoutSession>(sessionKey(sessionId), (previous) =>
          latestSessionSnapshot(previous, incoming),
        )
      },
      onError: (error) => {
        if (!active) return
        setFailure({ scope, error })
        // EventSource hides HTTP errors. A snapshot read detects deletion and also
        // recovers completion if the final event was lost before a disconnect.
        if (error instanceof ApplicantRequestError && error.code === 'connection_unavailable')
          void cache
            .fetchQuery({ ...sessionQueryOptions(client, sessionId), staleTime: 0 })
            .catch(() => {})
      },
    })
    return () => {
      active = false
      close()
    }
  }, [cache, client, sessionId, enabled, scope])
  return {
    error: queryError ?? (enabled && failure?.scope === scope ? failure.error : null),
    retry: () => setAttempt((value) => value + 1),
  }
}
