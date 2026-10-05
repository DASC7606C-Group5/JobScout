import { useMatchRoute } from '@tanstack/react-router'

import { useScoutSession } from '../../state/session-context'
import { Icon } from '../icon'

export function WorkspaceHeader() {
  const { session, busy, refresh, deleteSession } = useScoutSession()
  const matchRoute = useMatchRoute()
  const savedView = Boolean(matchRoute({ to: '/saved' }))
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
        <div className="flex items-center gap-2.5 text-xs">
          <button className="btn btn-ghost btn-sm" disabled={busy} onClick={refresh}>
            Refresh session
          </button>
          <button className="btn btn-ghost btn-sm" onClick={deleteSession}>
            Clear session
          </button>
        </div>
      )}
    </header>
  )
}
