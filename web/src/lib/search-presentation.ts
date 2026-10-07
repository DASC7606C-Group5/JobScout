import type { ScoutSession } from './contracts'
import { searchPhase } from './search-phase'

const profileStages: Record<string, string> = {
  ingest: 'Reading your information',
  extract: 'Reviewing your experience',
  profile: 'Reviewing your profile',
  validate: 'Checking your profile',
  clarify: 'Preparing questions',
  confirm: 'Preparing your summary',
}

export function searchPresentation(session: ScoutSession) {
  const limit = session.profile?.search_options.result_count ?? 10
  const promising = (session.recommendation?.jobs ?? []).filter(
    (item) =>
      item.analysis_status !== 'unavailable' &&
      (item.recommendation_fit === 'recommended' || item.recommendation_fit === 'possible'),
  ).length
  const completed = session.outcome === 'completed'
  const interrupted = session.outcome === 'failed'
  const phase = completed ? 'complete' : searchPhase(session)
  const comparing = promising >= limit
  const finishing = session.progress.retrieval_stopped && session.outcome === 'running'
  const activity = interrupted
    ? 'Search interrupted'
    : completed
      ? 'Search complete'
      : finishing
        ? 'Finishing the remaining job reviews'
        : comparing
          ? 'Comparing jobs to improve your list'
          : 'Checking jobs against your search criteria'
  return {
    phase,
    interrupted,
    comparing,
    finishing,
    canFinish: Boolean(session.run_id) && session.outcome === 'running' && !finishing,
    heading:
      phase === 'profile'
        ? profileStages[session.current_stage] || 'Reviewing your profile'
        : phase === 'preparing'
          ? 'Preparing your search'
          : completed
            ? 'Search results'
            : finishing
              ? 'Finishing your search'
              : comparing
                ? 'Comparing opportunities'
                : 'Finding jobs',
    activity,
  }
}
