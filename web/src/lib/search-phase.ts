import type { ScoutSession } from './contracts'

const jobSearchStages = new Set(['plan', 'search', 'review'])

export function searchPhase(session: ScoutSession) {
  if (session.run_id) return session.progress.retrieval_stopped ? 'review' : 'search'
  return jobSearchStages.has(session.current_stage) ? 'preparing' : 'profile'
}
