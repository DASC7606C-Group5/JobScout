import type { Dispatch, SetStateAction } from 'react'

import type { SummaryDraft } from '../lib/search-summary'
import { useScout, useScoutStore } from './scout-context'
import { useScoutSession } from './session-context'

export interface SessionDraftValues {
  clarification: {
    values: Record<string, string | string[]>
    skipped: string[]
    message: string
  }
  summary: { fields: SummaryDraft; message: string }
}

export type SessionDraftSection = keyof SessionDraftValues
export interface SessionDrafts {
  scope: string
  values: Partial<SessionDraftValues>
}

export function useSessionDraft<K extends SessionDraftSection>(
  section: K,
  initial: SessionDraftValues[K],
): [SessionDraftValues[K], Dispatch<SetStateAction<SessionDraftValues[K]>>] {
  const { session } = useScoutSession()
  const store = useScoutStore()
  const drafts = useScout((state) => state.sessionDrafts)
  const scope = `${session?.session_id ?? ''}:${session?.revision ?? 0}`
  const draft = drafts?.scope === scope ? (drafts.values[section] ?? initial) : initial

  function setDraft(update: SetStateAction<SessionDraftValues[K]>) {
    const latest = store.getState().sessionDrafts
    const current = latest?.scope === scope ? (latest.values[section] ?? initial) : initial
    store
      .getState()
      .saveSessionDraft(scope, section, typeof update === 'function' ? update(current) : update)
  }

  return [draft, setDraft]
}
