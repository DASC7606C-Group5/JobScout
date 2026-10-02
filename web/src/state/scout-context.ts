import { createContext, useContext } from 'react'
import { useStore } from 'zustand'

import type { ScoutState, ScoutStore } from './scout-store'

export const ScoutContext = createContext<ScoutStore | null>(null)

export function useScoutStore() {
  const store = useContext(ScoutContext)
  if (!store) throw new Error('ScoutProvider is required')
  return store
}

export function useScout<T>(selector: (state: ScoutState) => T): T {
  return useStore(useScoutStore(), selector)
}
