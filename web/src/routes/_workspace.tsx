import {
  createFileRoute,
  useBlocker,
  useParams,
  useRouter,
  useRouterState,
  redirect,
} from '@tanstack/react-router'

import { WorkspaceLayout } from '../components/layout/workspace-layout'
import { loadAccount } from '../lib/auth-client'
import { flushPendingDrafts, hasPendingDrafts } from '../state/draft-navigation'
import { ScoutProvider } from '../state/scout-provider'

export const Route = createFileRoute('/_workspace')({
  beforeLoad: async () => {
    if (!(await loadAccount())) throw redirect({ to: '/login' })
  },
  component: Workspace,
})

function Workspace() {
  const { sessionId } = useParams({ strict: false })
  const router = useRouter()
  const viewKey = useRouterState({ select: (state) => state.location.href })
  useBlocker({
    shouldBlockFn: async ({ current, next }) =>
      current.pathname !== next.pathname && !(await flushPendingDrafts()),
    enableBeforeUnload: hasPendingDrafts,
  })
  return (
    <ScoutProvider
      sessionId={sessionId ?? null}
      viewKey={viewKey}
      onSessionCreated={(id) => {
        if (router.state.location.pathname === '/new')
          void router.navigate({
            to: '/searches/$sessionId',
            params: { sessionId: id },
            search: {},
          })
      }}
      onSessionDeleted={(id) => {
        if (router.state.location.pathname === `/searches/${encodeURIComponent(id)}`)
          void router.navigate({ to: '/new' })
      }}
    >
      <WorkspaceLayout />
    </ScoutProvider>
  )
}
