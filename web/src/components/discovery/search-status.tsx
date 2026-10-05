import { applicantErrorMessage } from '../../lib/applicant-errors'
import type { ApplicantError, ScoutSession } from '../../lib/contracts'
import { Icon } from '../icon'
const stages: Record<string, string> = {
  ingest: 'Reading your information',
  extract: 'Reviewing your experience',
  validate: 'Checking your profile and preferences',
  clarify: 'Preparing details for you to confirm',
  confirm: 'Updating your search summary',
  plan: 'Preparing your search',
  search: 'Looking for roles that fit your search',
  retrieve: 'Looking for roles that fit your search',
  normalize: 'Organizing job listings',
  understand: 'Reviewing job requirements',
  check_result_count: 'Checking the number of matching jobs',
  recommend: 'Assessing job matches',
  present: 'Preparing your recommendations',
}
const activities: Record<string, string> = {
  search_started: 'Looking for roles that fit your search',
  search_jobs: 'Looking for roles that fit your search',
  source_completed: 'Comparing the roles found so far',
  fetch_job_details: 'Reading the full job listings',
  assess_candidates: 'Comparing job requirements with your experience',
  analysis_completed: 'Reviewing your matches',
  search_finished: 'Preparing your results',
}

export function SearchActivity({ session }: { session: ScoutSession }) {
  const { progress } = session
  if (!session.run_id || session.outcome !== 'running') return null
  const target = session.profile?.search_options.result_count ?? 10
  const matched = Math.min(progress.matched_count, target)
  const pending = Math.min(progress.pending_count, target - matched)
  return (
    <div className="w-full max-w-sm text-left">
      <output className="block text-sm">
        {matched + pending} {matched + pending === 1 ? 'role' : 'roles'} found
      </output>
      <p className="mt-2 text-xs text-base-content/60">
        {matched} with search conditions confirmed · {pending} to verify
      </p>
      <p className="mt-2 text-xs text-base-content/60">
        {progress.analyzed_count} {progress.analyzed_count === 1 ? 'job' : 'jobs'} reviewed ·
        Showing up to {target}
      </p>
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
  const activity = session.progress.events.at(-1)?.action
  const hasResults = Boolean(
    session.recommendation?.jobs.length || session.recommendation?.pending_jobs.length,
  )
  return (
    <section
      className={`card items-center justify-center border border-base-300 bg-base-100 text-center ${hasResults ? 'mb-6 p-5' : 'min-h-96 p-8'}`}
      aria-live="polite"
    >
      {!hasResults && (
        <span className="mb-6 flex size-20 items-center justify-center rounded-full bg-primary/20 text-primary-content">
          <span className="loading loading-lg loading-spinner" />
        </span>
      )}
      <h2 className="text-xl font-semibold">
        {(searching && activity && activities[activity]) ||
          stages[session.current_stage] ||
          'Finding and checking job matches'}
      </h2>
      <p className="mt-3 max-w-md text-sm leading-7 text-base-content/60">
        {searching
          ? 'You can explore available roles below or end the search whenever you’re ready.'
          : 'We’re organizing your experience and search criteria for you to review.'}
      </p>
      {searching && (
        <div className="mt-6 flex w-full justify-center">
          <SearchActivity session={session} />
        </div>
      )}
      {searching && (
        <button
          type="button"
          className="btn relative mt-6"
          disabled={stopping}
          aria-busy={stopping}
          onClick={onStop}
        >
          <span className={stopping ? 'invisible' : ''}>End search and view results</span>
          {stopping && <span className="absolute">Ending search…</span>}
        </button>
      )}
    </section>
  )
}
export function SearchFailure({
  errors,
  onRetry,
  onEdit,
  retryable,
}: {
  errors: ApplicantError[]
  onRetry: () => void
  onEdit: () => void
  retryable: boolean
}) {
  return (
    <section className="card border border-base-300 bg-base-100 p-6 sm:p-8">
      <span className="mb-5 flex size-12 items-center justify-center rounded-full bg-accent/50 text-accent-content">
        <Icon name="info" size={24} />
      </span>
      <h2 className="text-xl font-semibold">Something went wrong at this step</h2>
      {[...new Set(errors.length ? errors.map((error) => error.code) : ['request_failed'])].map(
        (code) => (
          <div key={code} role="alert">
            <p className="mt-3 text-sm leading-7 text-base-content/65">
              {applicantErrorMessage(code)}
            </p>
          </div>
        ),
      )}
      <div className="mt-7 flex flex-wrap gap-3">
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
