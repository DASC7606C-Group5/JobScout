import type { ScoutSession } from './contracts'

const jobSearchStages = new Set([
  'plan',
  'search',
  'retrieve',
  'review',
  'normalize',
  'understand',
  'check_result_count',
  'recommend',
  'present',
])

export function searchPhase(session: ScoutSession) {
  if (session.run_id) return session.progress.retrieval_stopped ? 'review' : 'search'
  return jobSearchStages.has(session.current_stage) ? 'preparing' : 'profile'
}
