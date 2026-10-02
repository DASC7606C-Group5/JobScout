import { createFileRoute } from '@tanstack/react-router'

import { WorkspaceLayout } from '../components/layout/workspace-layout'
import { ScoutProvider } from '../state/scout-provider'

export const Route = createFileRoute('/_workspace')({ component: Workspace })

function Workspace() {
  return (
    <ScoutProvider>
      <WorkspaceLayout />
    </ScoutProvider>
  )
}
