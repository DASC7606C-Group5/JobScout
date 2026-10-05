import { useMatchRoute, useNavigate } from '@tanstack/react-router'
import { useEffect, useRef } from 'react'

import { applicantErrorMessage } from '../../lib/applicant-errors'
import { SessionHttpError } from '../../lib/session-client'
import { useScoutSession } from '../../state/session-context'
import { Icon } from '../icon'

export function WorkspaceHeader() {
  const { session, deleting, deleteError, deleteSession } = useScoutSession()
  const dialog = useRef<HTMLDialogElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  const cancel = useRef<HTMLButtonElement>(null)
  const requested = useRef(false)
  const navigate = useNavigate()
  const matchRoute = useMatchRoute()
  const savedView = Boolean(matchRoute({ to: '/saved' }))
  useEffect(() => {
    if (!session && requested.current) {
      requested.current = false
      dialog.current?.close()
      void navigate({ to: '/', search: {} })
    }
  }, [session, navigate])
  return (
    <header className="flex min-h-20 flex-wrap items-center justify-between gap-3 border-b border-base-300 px-5 py-4 sm:px-8 xl:px-12">
      <p className="flex items-center gap-2 text-xs text-base-content/55">
        Workspace
        <Icon name="chevron" size={12} />
        <span className="text-base-content/85">
          {savedView ? 'Saved jobs' : 'Explore opportunities'}
        </span>
      </p>
      {session && (
        <button
          ref={trigger}
          className="btn btn-ghost btn-sm"
          disabled={deleting}
          onClick={() => {
            dialog.current?.showModal()
            cancel.current?.focus()
          }}
        >
          Start a new search
        </button>
      )}
      <dialog
        ref={dialog}
        className="modal"
        aria-labelledby="new-search-title"
        aria-describedby="new-search-consequence"
        onCancel={(event) => {
          if (deleting) event.preventDefault()
        }}
        onClose={() => {
          requested.current = false
          trigger.current?.focus()
        }}
      >
        <div className="modal-box">
          <h2 id="new-search-title" className="text-lg font-semibold">
            Start a new search?
          </h2>
          <p id="new-search-consequence" className="mt-3 text-sm leading-6 text-base-content/70">
            This will end your current search and remove its conversation and results. Your
            introduction, resume and saved jobs will stay in this tab.
          </p>
          {deleteError && (
            <p role="alert" className="mt-4 text-sm text-error">
              {deleteError instanceof SessionHttpError
                ? applicantErrorMessage(deleteError.code, deleteError.status)
                : applicantErrorMessage('connection_unavailable')}
            </p>
          )}
          <form method="dialog" className="modal-action" noValidate>
            <button type="submit" ref={cancel} className="btn btn-ghost" disabled={deleting}>
              Keep this search
            </button>
            <button
              type="button"
              className="btn btn-primary"
              disabled={deleting}
              onClick={() => {
                requested.current = true
                deleteSession()
              }}
            >
              {deleting && (
                <span className="loading loading-xs loading-spinner" aria-hidden="true" />
              )}
              Start a new search
            </button>
          </form>
        </div>
      </dialog>
    </header>
  )
}
