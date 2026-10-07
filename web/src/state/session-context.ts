import { createContext, useContext } from 'react'

import type { useSessionWorkflow } from './use-session-workflow'

type SessionContextValue = Omit<ReturnType<typeof useSessionWorkflow>, 'edit'> & {
  edit: () => void
}

export const SessionContext = createContext<SessionContextValue | null>(null)

export function useScoutSession() {
  const session = useContext(SessionContext)
  if (!session) throw new Error('ScoutProvider is required')
  return session
}
