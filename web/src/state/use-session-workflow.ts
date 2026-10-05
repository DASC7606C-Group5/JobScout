import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'

import type {
  CreateSessionRequest,
  ResumeSessionRequest,
  ResumeSubmission,
  ScoutInput,
  SessionClient,
} from '../lib/contracts'
import { SessionHttpError } from '../lib/session-client'
import { sessionKey, sessionQueryOptions } from '../lib/session-query'
import { readSessionId, rememberSessionId } from '../lib/session-storage'
import type { ScoutStore } from './scout-store'

type Command =
  | { kind: 'start'; input: CreateSessionRequest }
  | { kind: 'answer'; sessionId: string; request: ResumeSessionRequest }
  | { kind: 'delete'; sessionId: string }

type Operation = { command: Command; generation: number; controller: AbortController }

function recoveryFor(error: unknown) {
  if (!(error instanceof SessionHttpError)) return 'retry'
  switch (error.status) {
    case 404:
      return 'edit'
    case 409:
      return 'refresh'
    case 422:
      return 'correct'
    default:
      return 'retry'
  }
}

async function submitCommand(client: SessionClient, command: Command, signal: AbortSignal) {
  switch (command.kind) {
    case 'start':
      return client.start(command.input, signal)
    case 'answer':
      return client.answer(command.sessionId, command.request, signal)
    case 'delete':
      try {
        await client.delete(command.sessionId, signal)
      } catch (error) {
        // A lost DELETE response may be retried after the search was already removed.
        if (!(error instanceof SessionHttpError && error.status === 404)) throw error
      }
      return null
  }
}

export function useSessionWorkflow(store: ScoutStore, client: SessionClient) {
  const queryClient = useQueryClient()
  const [sessionId, setSessionId] = useState(readSessionId)
  const generation = useRef(0)
  const active = useRef<Operation | null>(null)
  const lastCommand = useRef<Command | null>(null)

  const mutation = useMutation({
    mutationKey: ['sessions', 'command'],
    retry: false,
    networkMode: 'always',
    gcTime: 0,
    mutationFn: ({ command, controller }: Operation) =>
      submitCommand(client, command, controller.signal),
    onSuccess: (session, operation) => {
      // Abandoned operations cannot restore a deleted or replaced session.
      if (operation.generation !== generation.current) return
      store.getState().clearSessionDrafts()
      rememberSessionId(session?.session_id ?? null)
      setSessionId(session?.session_id ?? null)
      if (session) queryClient.setQueryData(sessionKey(session.session_id), session)
      else store.getState().saveAnswers({})
      if (sessionId && sessionId !== session?.session_id)
        queryClient.removeQueries({ queryKey: sessionKey(sessionId), exact: true })
    },
    onError: (error, operation) => {
      if (operation.generation !== generation.current) return
      if (error instanceof SessionHttpError && error.status === 409 && sessionId) {
        lastCommand.current = null
        void queryClient.invalidateQueries({ queryKey: sessionKey(sessionId), exact: true })
      }
    },
    onSettled: (_data, _error, operation) => {
      if (operation.generation === generation.current) active.current = null
    },
  })

  const query = useQuery({
    ...sessionQueryOptions(client, sessionId),
    enabled: sessionId !== null && !mutation.isPending,
  })
  const session = query.data ?? null
  const pending = mutation.isPending || query.isFetching
  const busy = pending || session?.outcome === 'running'
  const deleting = mutation.isPending && mutation.variables?.command.kind === 'delete'
  const deleteError = mutation.variables?.command.kind === 'delete' ? mutation.error : null
  const error = (deleteError ? null : mutation.error) ?? query.error
  const profile = session?.profile

  useEffect(() => {
    if (!busy) store.getState().applyProfile(profile ?? null)
  }, [profile, busy, store])

  useEffect(
    () => () => {
      generation.current += 1
      active.current?.controller.abort()
    },
    [],
  )

  function execute(command: Command) {
    if (active.current) return
    const operation = {
      command,
      generation: ++generation.current,
      controller: new AbortController(),
    }
    active.current = operation
    lastCommand.current = command
    mutation.reset()
    void queryClient.cancelQueries({ queryKey: sessionKey(sessionId), exact: true })
    mutation.mutate(operation)
  }

  function start(input: ScoutInput) {
    if (busy) return
    store.getState().clearSessionDrafts()
    store.getState().saveAnswers({})
    execute({
      kind: 'start',
      input: { ...structuredClone(input), request_id: crypto.randomUUID() },
    })
  }

  function answer(submission: Partial<ResumeSubmission>) {
    if (!session || busy) return
    execute({
      kind: 'answer',
      sessionId: session.session_id,
      request: {
        message: '',
        answers: [],
        skipped_question_ids: [],
        profile_updates: {},
        action: 'answer',
        ...structuredClone(submission),
        request_id: crypto.randomUUID(),
        expected_revision: session.revision,
      },
    })
  }

  function reset() {
    generation.current += 1
    active.current?.controller.abort()
    active.current = null
    lastCommand.current = null
    mutation.reset()
    rememberSessionId(null)
    setSessionId(null)
    store.getState().clearSessionDrafts()
    store.getState().saveAnswers({})
    void queryClient.cancelQueries({ queryKey: sessionKey(sessionId), exact: true })
    queryClient.removeQueries({ queryKey: sessionKey(sessionId), exact: true })
  }

  function refresh() {
    if (!sessionId || pending) return
    mutation.reset()
    void query.refetch()
  }

  const recovery = recoveryFor(error)

  function retry() {
    if (pending) return
    if (recovery === 'edit') reset()
    else if (recovery === 'refresh' || query.isError) refresh()
    else if (recovery === 'correct') mutation.reset()
    else if (mutation.isError && lastCommand.current) execute(lastCommand.current)
    else if (session?.outcome === 'failed' && session.retryable) answer({ action: 'retry' })
  }

  function deleteSession() {
    if (!sessionId) return
    generation.current += 1
    active.current?.controller.abort()
    active.current = null
    execute({ kind: 'delete', sessionId })
  }

  return {
    session,
    busy,
    pending,
    deleting,
    deleteError,
    error,
    recovery,
    start,
    answer,
    retry,
    refresh,
    deleteSession,
    edit: () => (session ? answer({ action: 'edit_conditions' }) : reset()),
  }
}
