import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'

import { SessionHttpError } from '../lib/api-client'
import type {
  CancelSessionRequest,
  CreateSessionRequest,
  ResumeSessionRequest,
  ResumeSubmission,
  ScoutInput,
  ScoutSession,
  SessionClient,
  FeedbackRequest,
  FollowUpRequest,
  FollowUpSubmission,
  StopSessionRequest,
} from '../lib/contracts'
import { latestSessionSnapshot, sessionKey, sessionQueryOptions } from '../lib/session-query'
import { discardSessionDrafts, flushPendingDrafts } from './draft-navigation'
import { useSessionStream } from './use-session-stream'
import { historyKey } from './workspace-queries'

type Command = (
  | { kind: 'start'; input: CreateSessionRequest }
  | { kind: 'answer'; sessionId: string; request: ResumeSessionRequest }
  | { kind: 'stop'; sessionId: string; request: StopSessionRequest }
  | { kind: 'delete'; sessionId: string }
  | { kind: 'cancel'; sessionId: string; request: CancelSessionRequest }
  | { kind: 'feedback'; sessionId: string; request: FeedbackRequest }
  | { kind: 'follow_up'; sessionId: string; request: FollowUpRequest }
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
    case 'cancel':
      return client.cancel(command.sessionId, command.request)
    case 'stop':
      return client.stop(command.sessionId, command.request)
    case 'feedback':
      return client.feedback(command.sessionId, command.request)
    case 'follow_up':
      return client.followUp(command.sessionId, command.request)
    case 'delete':
      await client.delete(command.sessionId)
      return null
  }
}

function sessionAvailability(
  session: ScoutSession | null,
  preparing: boolean,
  mutating: boolean,
  loading: boolean,
) {
  const pending = preparing || mutating || loading
  return {
    pending,
    busy: pending || session?.outcome === 'running' || session?.outcome === 'queued',
    canEdit:
      session !== null &&
      !preparing &&
      !mutating &&
      session.outcome !== 'queued' &&
      (session.outcome !== 'running' || Boolean(session.run_id)),
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
      if (
        command.kind === 'answer' ||
        (command.kind === 'follow_up' && command.request.action === 'answer')
      )
        discardSessionDrafts(command.sessionId, command.request.expected_revision)
      if (command.kind === 'start' && session && command.origin === activeOrigin.current)
        onSessionCreated?.(session.session_id)
      if (command.kind === 'delete') {
        discardSessionDrafts(command.sessionId)
        cache.removeQueries({ queryKey: sessionKey(command.sessionId), exact: true })
        onSessionDeleted?.(command.sessionId)
      }
      void cache.invalidateQueries({ queryKey: historyKey })
      void cache.invalidateQueries({ queryKey: ['model-usage'] })
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
  const stream = useSessionStream(client, session, command.pending, query.error)
  const { pending, busy, canEdit } = sessionAvailability(
    session,
    preparing === origin,
    command.pending,
    query.isFetching,
  )
  const error = command.error ?? stream.error
  const recovery = recoveryFor(error)
  const outcome = session?.outcome
  useEffect(() => {
    if (sessionId && outcome) void cache.invalidateQueries({ queryKey: ['model-usage'] })
    if (sessionId && outcome && outcome !== 'running' && outcome !== 'queued')
      void cache.invalidateQueries({ queryKey: historyKey })
  }, [cache, sessionId, outcome])

  async function execute(command: Command) {
    const scope = operationScope(command)
    if (inFlight.current.has(scope)) return false
    inFlight.current.add(scope)
    previous.current.set(commandScope(command), command)
    let succeeded = false
    try {
      await cache.cancelQueries({
        queryKey: sessionKey(command.kind === 'start' ? null : command.sessionId),
        exact: true,
      })
      await mutation.mutateAsync(command)
      succeeded = true
    } catch {
      // The mutation exposes the request error to the notification layer.
    }
    inFlight.current.delete(scope)
    return succeeded
  }

  async function prepare(command: Command) {
    const scope = operationScope(command)
    if (preparations.current.has(scope) || inFlight.current.has(scope)) return
    preparations.current.add(scope)
    setPreparing(command.origin)
    const saved = await flushPendingDrafts()
    preparations.current.delete(scope)
    setPreparing((current) => (current === command.origin ? null : current))
    return saved && command.origin === activeOrigin.current ? execute(command) : false
  }

  async function start(input: ScoutInput) {
    if (busy) return
    return prepare({
      kind: 'start',
      origin,
      input: { ...structuredClone(input), request_id: crypto.randomUUID() },
    })
  }

  async function feedback(jobId: string, reaction: FeedbackRequest['reaction']) {
    if (!session || busy || session.outcome !== 'completed') return false
    return execute({
      kind: 'feedback',
      origin,
      sessionId: session.session_id,
      request: {
        request_id: crypto.randomUUID(),
        expected_revision: session.revision,
        job_id: jobId,
        reaction,
      },
    })
  }

  async function followUp(request: FollowUpSubmission) {
    if (!session || busy) return false
    return prepare({
      kind: 'follow_up',
      origin,
      sessionId: session.session_id,
      request: {
        ...structuredClone(request),
        request_id: crypto.randomUUID(),
        expected_revision: session.revision,
      } as FollowUpRequest,
    })
  }

  async function answer(submission: Partial<ResumeSubmission>) {
    if (!session || (submission.action === 'edit_conditions' ? !canEdit : busy)) return
    if (
      session.current_stage === 'follow_up_clarify' &&
      (!submission.action || submission.action === 'answer')
    ) {
      return followUp({
        action: 'answer',
        answers: submission.answers ?? [],
        skipped_question_ids: submission.skipped_question_ids ?? [],
        message: submission.message ?? '',
      })
    }
    return prepare({
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
    stream.retry()
    return query.refetch()
  }

  function stop() {
    if (!session?.run_id || session.outcome !== 'running' || command.pending) return
    return execute({
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

  function cancel() {
    if (!session?.operation_id || session.outcome !== 'queued' || command.pending) return
    return execute({
      kind: 'cancel',
      origin,
      sessionId: session.session_id,
      request: {
        request_id: crypto.randomUUID(),
        expected_revision: session.revision,
        operation_id: session.operation_id,
      },
    })
  }

  function retry() {
    if (pending) return
    if (recovery === 'refresh' || stream.error) return refresh()
    else if (recovery === 'correct') mutation.reset()
    else if (command.error && previous.current.has(key)) return execute(previous.current.get(key)!)
    else if (
      session &&
      (session.outcome === 'failed' || session.outcome === 'cancelled') &&
      session.retryable
    )
      return answer({ action: 'retry' })
  }

  function deleteSession(id = sessionId) {
    if (id) return execute({ kind: 'delete', sessionId: id, origin })
  }

  return {
    session,
    busy,
    canEdit,
    pending,
    deleting: command.deleting,
    deleteError: command.deleteError,
    error,
    recovery,
    start,
    answer,
    stop,
    cancel,
    cancelling: command.pending && mutation.variables?.kind === 'cancel',
    feedback,
    followUp,
    stopping: command.pending && mutation.variables?.kind === 'stop',
    retry,
    refresh,
    deleteSession,
    edit: () => {
      if (session) return answer({ action: 'edit_conditions' })
    },
  }
}
