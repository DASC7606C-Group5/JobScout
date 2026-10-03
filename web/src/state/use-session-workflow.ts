import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'

import type { ScoutInput, SessionClient } from '../lib/contracts'
import { toScoutInput } from '../lib/profile-form'
import { SessionHttpError } from '../lib/session-client'
import { sessionKey, sessionQueryOptions } from '../lib/session-query'
import type { ScoutStore } from './scout-store'

type Command =
  | { kind: 'start'; input: ScoutInput }
  | { kind: 'answer'; sessionId: string; answers: Record<string, string> }
  | { kind: 'delete'; sessionId: string }

type Operation = { command: Command; revision: number; controller: AbortController }

export function useSessionWorkflow(store: ScoutStore, client: SessionClient) {
  const queryClient = useQueryClient()
  const [sessionId, setSessionId] = useState<string | null>(null)
  const revision = useRef(0)
  const active = useRef<Operation | null>(null)
  const lastCommand = useRef<Command | null>(null)

  const mutation = useMutation({
    mutationKey: ['sessions', 'command'],
    retry: false,
    networkMode: 'always',
    gcTime: 0,
    mutationFn: async ({ command, controller }: Operation) => {
      const signal = controller.signal
      switch (command.kind) {
        case 'start':
          return client.start(command.input, signal)
        case 'answer':
          return client.answer(command.sessionId, command.answers, signal)
        case 'delete':
          await client.delete(command.sessionId, signal)
          return null
      }
    },
    onSuccess: (session, operation) => {
      // An abandoned request must never restore a session or replace a newer draft.
      if (operation.revision !== revision.current) return
      if (session) {
        queryClient.setQueryData(sessionKey(session.session_id), session)
        setSessionId(session.session_id)
      } else {
        setSessionId(null)
        store.getState().saveAnswers({})
      }
      if (sessionId && sessionId !== session?.session_id)
        queryClient.removeQueries({ queryKey: sessionKey(sessionId), exact: true })
    },
    onSettled: (_data, _error, operation) => {
      if (operation.revision === revision.current) active.current = null
    },
  })

  const query = useQuery({
    ...sessionQueryOptions(client, sessionId),
    enabled: sessionId !== null && !mutation.isPending,
  })
  const session = query.data ?? null
  const busy = mutation.isPending || query.isFetching
  const error = mutation.error ?? query.error
  const profile = session?.profile

  useEffect(() => {
    if (!busy) store.getState().applyProfile(profile ?? null)
  }, [profile, busy, store])

  useEffect(
    () => () => {
      revision.current += 1
      active.current?.controller.abort()
    },
    [],
  )

  function execute(command: Command) {
    if (active.current || query.isFetching) return
    const operation = {
      command,
      revision: ++revision.current,
      controller: new AbortController(),
    }
    active.current = operation
    lastCommand.current = command
    mutation.reset()
    // Cancel a background GET before a mutation can update the cached snapshot.
    void queryClient.cancelQueries({ queryKey: sessionKey(sessionId), exact: true })
    mutation.mutate(operation)
  }

  function start(input: ScoutInput) {
    if (active.current || query.isFetching) return
    store.getState().saveAnswers({})
    execute({ kind: 'start', input: structuredClone(input) })
  }

  function answer(answers: Record<string, string>) {
    if (!sessionId || active.current || query.isFetching) return
    store.getState().saveAnswers(answers)
    execute({ kind: 'answer', sessionId, answers: { ...answers } })
  }

  function edit() {
    revision.current += 1
    active.current?.controller.abort()
    active.current = null
    lastCommand.current = null
    mutation.reset()
    setSessionId(null)
    store.getState().saveAnswers({})
    void queryClient.cancelQueries({ queryKey: sessionKey(sessionId), exact: true })
    queryClient.removeQueries({ queryKey: sessionKey(sessionId), exact: true })
  }

  function refresh() {
    if (!sessionId || busy) return
    mutation.reset()
    void query.refetch()
  }

  const recovery =
    error instanceof SessionHttpError && (error.status === 404 || error.status === 422)
      ? 'edit'
      : error instanceof SessionHttpError && error.status === 409
        ? 'refresh'
        : 'retry'

  function retry() {
    if (busy) return
    if (recovery === 'edit') edit()
    else if (recovery === 'refresh' || query.isError) refresh()
    else if (mutation.isError && lastCommand.current) execute(lastCommand.current)
    else if (session?.outcome === 'failed') start(toScoutInput(store.getState().draft))
  }

  return {
    session,
    busy,
    error,
    recovery,
    start,
    answer,
    retry,
    edit,
    refresh,
    deleteSession: () => {
      if (sessionId) execute({ kind: 'delete', sessionId })
    },
  }
}
