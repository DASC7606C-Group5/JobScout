import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'

import type {
  CreateSessionRequest,
  ResumeSessionRequest,
  ResumeSubmission,
  ScoutInput,
  ScoutSession,
  SessionClient,
  StopSessionRequest,
} from '../lib/contracts'
import { SessionHttpError } from '../lib/session-client'
import { latestSessionSnapshot, sessionKey, sessionQueryOptions } from '../lib/session-query'
import { discardSessionDrafts, flushPendingDrafts } from './draft-navigation'
import { historyKey } from './workspace-queries'

type Command = (
  | { kind: 'start'; input: CreateSessionRequest }
  | { kind: 'answer'; sessionId: string; request: ResumeSessionRequest }
  | { kind: 'stop'; sessionId: string; request: StopSessionRequest }
  | { kind: 'delete'; sessionId: string }
) & { origin: object }

const commandScope = (command: Command) => (command.kind === 'start' ? 'new' : command.sessionId)
const operationScope = (command: Command) =>
  command.kind === 'start' ? command.origin : command.sessionId

function commandStatus(
  command: Command | undefined,
  sessionId: string | null,
  isPending: boolean,
  error: Error | null,
  origin: object,
) {
  const current =
    command !== undefined &&
    command.origin === origin &&
    commandScope(command) === (sessionId ?? 'new')
  const pending = current && isPending
  const deleting = pending && command?.kind === 'delete'
  const deleteError = current && command?.kind === 'delete' ? error : null
  return { pending, deleting, deleteError, error: current && !deleteError ? error : null }
}

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

async function submitCommand(client: SessionClient, command: Command) {
  switch (command.kind) {
    case 'start':
      return client.start(command.input)
    case 'answer':
      return client.answer(command.sessionId, command.request)
    case 'stop':
      return client.stop(command.sessionId, command.request)
    case 'delete':
      await client.delete(command.sessionId)
      return null
  }
}

export function useSessionWorkflow(
  client: SessionClient,
  sessionId: string | null,
  viewKey: string,
  onSessionCreated?: (id: string) => void,
  onSessionDeleted?: (id: string) => void,
) {
  const cache = useQueryClient()
  const origin = useMemo(() => ({ viewKey }), [viewKey])
  const activeOrigin = useRef(origin)
  useLayoutEffect(() => {
    activeOrigin.current = origin
  }, [origin])
  const inFlight = useRef(new Set<string | object>())
  const preparations = useRef(new Set<string | object>())
  const [preparing, setPreparing] = useState<object | null>(null)
  const previous = useRef(new Map<string, Command>())
  const key = sessionId ?? 'new'
  const mutation = useMutation({
    mutationKey: ['session-command'],
    retry: false,
    networkMode: 'always',
    mutationFn: (command: Command) => submitCommand(client, command),
    onSuccess: (session, command) => {
      if (session)
        cache.setQueryData<ScoutSession>(sessionKey(session.session_id), (previous) =>
          latestSessionSnapshot(previous, session),
        )
      if (command.kind === 'answer')
        discardSessionDrafts(command.sessionId, command.request.expected_revision)
      if (command.kind === 'start' && session && command.origin === activeOrigin.current)
        onSessionCreated?.(session.session_id)
      if (command.kind === 'delete') {
        discardSessionDrafts(command.sessionId)
        cache.removeQueries({ queryKey: sessionKey(command.sessionId), exact: true })
        onSessionDeleted?.(command.sessionId)
      }
      void cache.invalidateQueries({ queryKey: historyKey })
    },
    onError: (error, command) => {
      if (error instanceof SessionHttpError && error.status === 409 && command.kind !== 'start') {
        previous.current.delete(commandScope(command))
        void cache.invalidateQueries({ queryKey: sessionKey(command.sessionId), exact: true })
      }
    },
    onSettled: (_data, _error, command) => {
      inFlight.current.delete(operationScope(command))
    },
  })
  const command = commandStatus(
    mutation.variables,
    sessionId,
    mutation.isPending,
    mutation.error,
    origin,
  )
  const query = useQuery({
    ...sessionQueryOptions(client, sessionId),
    enabled: sessionId !== null && !command.pending,
  })
  const session = query.data ?? null
  const pending = preparing === origin || command.pending || query.isFetching
  const busy = pending || session?.outcome === 'running'
  const error = command.error ?? query.error
  const recovery = recoveryFor(error)
  const outcome = session?.outcome
  useEffect(() => {
    if (sessionId && outcome && outcome !== 'running')
      void cache.invalidateQueries({ queryKey: historyKey })
  }, [cache, sessionId, outcome])

  function execute(command: Command) {
    const scope = operationScope(command)
    if (inFlight.current.has(scope)) return
    inFlight.current.add(scope)
    previous.current.set(commandScope(command), command)
    void cache
      .cancelQueries({
        queryKey: sessionKey(command.kind === 'start' ? null : command.sessionId),
        exact: true,
      })
      .then(() => mutation.mutate(command))
  }

  async function prepare(command: Command) {
    const scope = operationScope(command)
    if (preparations.current.has(scope) || inFlight.current.has(scope)) return
    preparations.current.add(scope)
    setPreparing(command.origin)
    const saved = await flushPendingDrafts()
    preparations.current.delete(scope)
    setPreparing((current) => (current === command.origin ? null : current))
    if (saved && command.origin === activeOrigin.current) execute(command)
  }

  async function start(input: ScoutInput) {
    if (busy) return
    await prepare({
      kind: 'start',
      origin,
      input: { ...structuredClone(input), request_id: crypto.randomUUID() },
    })
  }

  async function answer(submission: Partial<ResumeSubmission>) {
    if (!session || busy) return
    await prepare({
      kind: 'answer',
      origin,
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

  function refresh() {
    if (!sessionId || pending) return
    mutation.reset()
    void query.refetch()
  }

  function stop() {
    if (!session?.run_id || session.outcome !== 'running' || command.pending) return
    execute({
      kind: 'stop',
      origin,
      sessionId: session.session_id,
      request: {
        request_id: crypto.randomUUID(),
        expected_revision: session.revision,
        run_id: session.run_id,
      },
    })
  }

  function retry() {
    if (pending) return
    if (recovery === 'refresh' || query.isError) refresh()
    else if (recovery === 'correct') mutation.reset()
    else if (command.error && previous.current.has(key)) execute(previous.current.get(key)!)
    else if (session?.outcome === 'failed' && session.retryable) void answer({ action: 'retry' })
  }

  function deleteSession(id = sessionId) {
    if (id) execute({ kind: 'delete', sessionId: id, origin })
  }

  return {
    session,
    busy,
    pending,
    deleting: command.deleting,
    deleteError: command.deleteError,
    error,
    recovery,
    start,
    answer,
    stop,
    stopping: command.pending && mutation.variables?.kind === 'stop',
    retry,
    refresh,
    deleteSession,
    edit: () => {
      if (session) void answer({ action: 'edit_conditions' })
    },
  }
}
