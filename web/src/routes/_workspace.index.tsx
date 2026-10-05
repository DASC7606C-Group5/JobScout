import { useQuery } from '@tanstack/react-query'
import { createFileRoute, useNavigate } from '@tanstack/react-router'
import { useEffect, useState } from 'react'

import { applicantErrorMessage } from '../lib/applicant-errors'
import { sessionClient, SessionHttpError } from '../lib/session-client'
import { sessionQueryOptions } from '../lib/session-query'
import { readSessionId, rememberSessionId } from '../lib/session-storage'
import { useSessionHistory } from '../state/workspace-queries'

export const Route = createFileRoute('/_workspace/')({
  component: WorkspaceHome,
})

function WorkspaceHome() {
  const [remembered] = useState(readSessionId)
  const recovered = useQuery(sessionQueryOptions(sessionClient, remembered))
  const history = useSessionHistory()
  const navigate = useNavigate()
  const missing = recovered.error instanceof SessionHttpError && recovered.error.status === 404
  const latest = history.data?.pages[0]?.items[0]?.session_id
  useEffect(() => {
    if (recovered.data) {
      void navigate({
        to: '/searches/$sessionId',
        params: { sessionId: recovered.data.session_id },
        search: {},
        replace: true,
      })
    } else if ((!remembered || missing) && history.isSuccess) {
      if (missing) rememberSessionId(null)
      if (latest)
        void navigate({
          to: '/searches/$sessionId',
          params: { sessionId: latest },
          search: {},
          replace: true,
        })
      else void navigate({ to: '/new', replace: true })
    }
  }, [recovered.data, remembered, missing, history.isSuccess, latest, navigate])
  if ((recovered.isError && !missing) || history.isError)
    return (
      <div className="alert alert-error" role="alert">
        <span>{applicantErrorMessage('connection_unavailable')}</span>
        <button
          className="btn btn-sm"
          onClick={() => {
            void recovered.refetch()
            void history.refetch()
          }}
        >
          Retry
        </button>
      </div>
    )
  return (
    <output className="flex min-h-40 items-center gap-3" aria-live="polite">
      <span className="loading loading-spinner" aria-hidden="true" />
      Loading your workspace…
    </output>
  )
}
