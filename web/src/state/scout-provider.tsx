import { useState, type ReactNode } from 'react'

import { sessionClient } from '../lib/session-client'
import { ScoutContext } from './scout-context'
import { createScoutStore } from './scout-store'

export function ScoutProvider({ children }: { children: ReactNode }) {
  const [store] = useState(() => createScoutStore(sessionClient))
  return <ScoutContext value={store}>{children}</ScoutContext>
}
