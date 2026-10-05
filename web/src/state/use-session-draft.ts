import type { SummaryDraft } from '../lib/search-summary'
import { sessionDraftPath } from '../lib/workspace-client'
import { useScoutSession } from './session-context'
import { usePersistedDraft } from './use-persisted-draft'

export interface SessionDraftValues {
  clarification: { values: Record<string, string | string[]>; skipped: string[]; message: string }
  summary: { fields: SummaryDraft; message: string }
}
export type SessionDraftSection = keyof SessionDraftValues

export function useSessionDraft<K extends SessionDraftSection>(
  section: K,
  initial: SessionDraftValues[K],
) {
  const { session } = useScoutSession()
  if (!session) throw new Error('A session is required to edit its draft.')
  return usePersistedDraft(sessionDraftPath(session.session_id, session.revision, section), initial)
}
