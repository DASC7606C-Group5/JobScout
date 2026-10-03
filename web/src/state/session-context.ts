import { createContext, useContext } from 'react'

import type { useSessionWorkflow } from './use-session-workflow'

export const SessionContext = createContext<ReturnType<typeof useSessionWorkflow> | null>(null)

export function useScoutSession() {
  const session = useContext(SessionContext)
  if (!session) throw new Error('ScoutProvider is required')
  return session
}
