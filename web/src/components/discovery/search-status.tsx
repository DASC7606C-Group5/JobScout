import { applicantErrorMessage } from '../../lib/applicant-errors'
import type { ApplicantError, ScoutSession } from '../../lib/contracts'
import { searchPhase } from '../../lib/search-phase'
import { Icon } from '../icon'
const profileStages: Record<string, string> = {
  ingest: 'Reading your information',
  extract: 'Reviewing your experience',
  profile: 'Reviewing your profile',
  validate: 'Checking your profile',
  clarify: 'Preparing questions',
  confirm: 'Preparing your summary',
}
const stages: Record<string, string> = {
  plan: 'Preparing your search',
  search: 'Searching for jobs',
  retrieve: 'Searching for jobs',
  review: 'Reviewing jobs',
  normalize: 'Organizing listings',
  understand: 'Reading requirements',
  check_result_count: 'Checking matches',
  recommend: 'Assessing matches',
  present: 'Preparing results',
}
const activities: Record<string, string> = {
  search_started: 'Searching for jobs',
  search_jobs: 'Searching for jobs',
  source_completed: 'Reviewing jobs',
  fetch_job_details: 'Reading job listings',
  assess_candidates: 'Reviewing jobs',
  analysis_completed: 'Reviewing jobs',
  search_finished: 'Preparing results',
}

function loadingCopy(session: ScoutSession) {
  const phase = searchPhase(session)
  if (phase === 'profile')
    return {
      heading: profileStages[session.current_stage] || 'Reviewing your profile',
      description: 'Checking your experience and preferences.',
    }
  if (phase === 'preparing')
    return { heading: 'Preparing your search', description: 'Getting ready to find jobs.' }
  if (session.progress.retrieval_stopped)
    return { heading: 'Reviewing jobs', description: 'Search ended. Reviews continue.' }
  const activity = session.progress.events.at(-1)?.action
  const heading =
    (session.run_id && activity && activities[activity]) ||
    stages[session.current_stage] ||
    'Searching for jobs'
  return {
    heading,
    description: 'Browse jobs while we search.',
  }
}

export function SearchActivity({ session }: { session: ScoutSession }) {
  const { progress } = session
  if (searchPhase(session) === 'profile' || session.outcome !== 'running') return null
  const target = session.profile?.search_options.result_count ?? 10
  const matched = Math.min(progress.matched_count, target)
  const pending = Math.min(progress.pending_count, target - matched)
  const stats = [
    {
      count: matched + pending,
      label: 'Found',
      icon: 'search' as const,
      tone: 'bg-primary/20 text-primary-content',
    },
    {
      count: progress.analyzed_count,
      label: 'Reviewed',
      icon: 'check' as const,
      tone: 'bg-secondary/25 text-secondary-content',
    },
    {
      count: matched,
      label: 'Confirmed',
      icon: 'briefcase' as const,
      tone: 'bg-base-200 text-base-content',
    },
    {
      count: pending,
      label: 'Pending',
      icon: 'clock' as const,
      tone: 'bg-warning/25 text-warning-content',
    },
  ]
  return (
    <div className="grid w-full max-w-2xl grid-cols-2 gap-4 sm:grid-cols-4">
      {stats.map(({ count, label, icon, tone }) => (
        <div key={label} className="flex items-center gap-2.5">
          <span className={`flex size-9 shrink-0 items-center justify-center rounded-full ${tone}`}>
            <Icon name={icon} size={17} />
          </span>
          <div>
            <output className="block text-lg leading-6 font-semibold tabular-nums">{count}</output>
            <span className="mt-0.5 block text-xs leading-4 text-base-content/70">{label}</span>
          </div>
        </div>
      ))}
    </div>
  )
}

export function SearchLoading({
  session,
  onStop,
  stopping,
}: {
  session: ScoutSession
  onStop: () => void
  stopping: boolean
}) {
  const searching = Boolean(session.run_id)
  const jobSearch = searchPhase(session) !== 'profile'
  const retrievalStopped = session.progress.retrieval_stopped
  const { heading, description } = loadingCopy(session)
  return (
    <section
      className="card mb-6 border border-base-300 bg-base-100 p-5 sm:p-6"
      aria-label="Search progress"
    >
      <div
        className={`grid grid-cols-[auto_minmax(0,1fr)] items-center gap-x-4 gap-y-5 ${jobSearch ? 'sm:grid-cols-[auto_minmax(0,1fr)_11rem]' : ''}`}
      >
        <span
          className="flex size-12 items-center justify-center rounded-full bg-primary/20 text-primary-content"
          aria-hidden="true"
        >
          <span className="loading loading-md loading-spinner" />
        </span>
        <div
          aria-live="polite"
          className="flex min-h-28 min-w-0 flex-col justify-center md:min-h-16"
        >
          <h2 key={heading} className="status-copy text-lg font-semibold sm:text-xl">
            {heading}
          </h2>
          <p className="mt-1 text-sm leading-6 text-base-content/65">{description}</p>
        </div>
        {jobSearch && (
          <div className="col-span-2 sm:col-span-3 sm:pl-16">
            <SearchActivity session={session} />
          </div>
        )}
        {jobSearch && (
          <div className="col-span-2 flex min-h-12 items-center sm:col-span-1 sm:col-start-3 sm:row-start-1 sm:justify-end">
            {searching && !retrievalStopped && (
              <button
                type="button"
                className="btn relative w-44"
                disabled={stopping}
                aria-busy={stopping}
                onClick={onStop}
              >
                <span className={stopping ? 'invisible' : ''}>End search</span>
                {stopping && <span className="absolute">Ending search…</span>}
              </button>
            )}
          </div>
        )}
      </div>
    </section>
  )
}
export function SearchFailure({
  errors,
  onRetry,
  onEdit,
  retryable,
  compact = false,
}: {
  errors: ApplicantError[]
  onRetry: () => void
  onEdit: () => void
  retryable: boolean
  compact?: boolean
}) {
  return (
    <section
      className={`card border border-base-300 bg-base-100 ${compact ? 'mb-6 p-4 sm:p-5' : 'p-6 sm:p-8'}`}
    >
      {!compact && (
        <span className="mb-5 flex size-12 items-center justify-center rounded-full bg-accent/50 text-accent-content">
          <Icon name="info" size={24} />
        </span>
      )}
      <h2
        className={
          compact ? 'flex items-center gap-2 text-base font-semibold' : 'text-xl font-semibold'
        }
      >
        {compact && <Icon name="info" size={18} />}{' '}
        {compact ? 'Search interrupted' : 'Something went wrong at this step'}
      </h2>
      {[...new Set(errors.length ? errors.map((error) => error.code) : ['request_failed'])].map(
        (code) => (
          <div key={code} role="alert">
            <p className={`${compact ? 'mt-2' : 'mt-3'} text-sm leading-7 text-base-content/65`}>
              {applicantErrorMessage(code)}
            </p>
          </div>
        ),
      )}
      <div className={`${compact ? 'mt-3' : 'mt-7'} flex flex-wrap gap-3`}>
        {retryable && (
          <button className="btn border-0 btn-primary" onClick={onRetry}>
            Try again
            <Icon name="arrow" size={17} />
          </button>
        )}
        <button className="btn" onClick={onEdit}>
          Edit search criteria
        </button>
      </div>
    </section>
  )
}
