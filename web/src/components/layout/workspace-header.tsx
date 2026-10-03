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
        工作空间
        <Icon name="chevron" size={12} />
        <span className="text-base-content/85">{savedView ? '收藏岗位' : '发现机会'}</span>
      </p>
      {session && (
        <div className="flex items-center gap-2.5 text-xs">
          <button className="btn btn-ghost btn-sm" disabled={busy} onClick={refresh}>
            刷新会话
          </button>
          <button className="btn btn-ghost btn-sm" disabled={busy} onClick={deleteSession}>
            清除会话
          </button>
        </div>
      )}
    </header>
  )
}
