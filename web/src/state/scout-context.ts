import { createContext, useContext } from 'react'

import type { RecommendationItem } from '../lib/contracts'

export interface ScoutState {
  saved: RecommendationItem[]
  announcement: string
  saveError: string
  clearSaveError: () => void
  toggleSaved: (item: RecommendationItem) => Promise<boolean>
}

export const ScoutContext = createContext<ScoutState | null>(null)

export function useScout<T>(selector: (state: ScoutState) => T): T {
  const state = useContext(ScoutContext)
  if (!state) throw new Error('ScoutProvider is required')
  return selector(state)
}
