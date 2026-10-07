import { useNavigate } from '@tanstack/react-router'
import { useEffect, useEffectEvent } from 'react'

import { applicantErrorMessage } from '../../lib/applicant-errors'
import { requestErrorMessage } from '../../lib/request-errors'
import { useNotification, useNotifications } from '../../state/notifications'
import { useScoutSession } from '../../state/session-context'
import { useSavedJobs, useSessionHistory } from '../../state/workspace-queries'

export function WorkspaceNotifications() {
  const { session, error, recovery, retry, edit } = useScoutSession()
  const history = useSessionHistory()
  const saved = useSavedJobs()
  const navigate = useNavigate()
  const { notify, dismiss } = useNotifications()
  useNotification(error, {
    id: `session-request:${session?.session_id ?? 'new'}`,
    message: requestErrorMessage(error),
    tone: 'error',
    actions: [
      {
        label:
          recovery === 'edit'
            ? 'Start over'
            : recovery === 'refresh'
              ? 'Reload search'
              : recovery === 'correct'
                ? 'Edit submission'
                : 'Retry',
        onClick: () => (recovery === 'edit' ? navigate({ to: '/new' }) : retry()),
      },
    ],
  })
  useNotification(history.error, {
    id: 'search-history',
    message: 'Could not load your search history.',
    tone: 'error',
    actions: [{ label: 'Try again', onClick: () => history.refetch() }],
  })
  useNotification(saved.error, {
    id: 'saved-jobs',
    message: saved.data
      ? 'Saved jobs could not be refreshed. Showing the last loaded list.'
      : 'Saved jobs could not be loaded. Your saved jobs are still kept in the workspace.',
    tone: saved.data ? 'warning' : 'error',
    actions: [{ label: 'Retry', onClick: () => saved.refetch() }],
  })
  const failure =
    session?.outcome === 'failed'
      ? JSON.stringify([
          session.session_id,
          session.run_id,
          session.errors.map((item) => item.code),
        ])
      : null
  const showFailure = useEffectEvent(() => {
    if (!session) return
    const codes = [
      ...new Set(
        session.errors.length ? session.errors.map((item) => item.code) : ['request_failed'],
      ),
    ]
    const ids: string[] = []
    for (const code of codes) {
      const id = `search-failure:${session.session_id}:${code}`
      ids.push(id)
      notify({
        id,
        message: applicantErrorMessage(code),
        tone: 'error',
        actions: [
          ...(code === 'model_unavailable'
            ? [{ label: 'Model settings', onClick: () => navigate({ to: '/settings' }) }]
            : []),
          ...(session.retryable ? [{ label: 'Try again', onClick: retry }] : []),
          { label: 'Edit search criteria', onClick: edit },
        ],
      })
    }
    return ids
  })
  useEffect(() => {
    if (!failure) return
    const ids = showFailure()
    return () => {
      for (const id of ids ?? []) dismiss(id)
    }
  }, [failure, dismiss])
  return null
}
