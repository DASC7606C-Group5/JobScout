import { useState, type ReactNode } from 'react'

import type { SessionClient } from '../lib/contracts'
import { sessionClient } from '../lib/session-client'
import { ScoutContext } from './scout-context'
import { createScoutStore } from './scout-store'
import { SessionContext } from './session-context'
import { useSessionWorkflow } from './use-session-workflow'

export function ScoutProvider({
  children,
  client = sessionClient,
}: {
  children: ReactNode
  client?: SessionClient
}) {
  const [store] = useState(createScoutStore)
  const workflow = useSessionWorkflow(store, client)
  return (
    <ScoutContext value={store}>
      <SessionContext value={workflow}>{children}</SessionContext>
    </ScoutContext>
  )
}
