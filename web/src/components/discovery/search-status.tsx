import { applicantErrorMessage } from '../../lib/applicant-errors'
import type { ApplicantError } from '../../lib/contracts'
import { Icon } from '../icon'
const stages: Record<string, string> = {
  ingest: 'Reading your information',
  extract: 'Reviewing your experience',
  validate: 'Checking your profile and preferences',
  clarify: 'Preparing details for you to confirm',
  confirm: 'Updating your search summary',
  plan: 'Preparing your search',
  search: 'Searching supported job sources',
  retrieve: 'Searching supported job sources',
  normalize: 'Organizing job listings',
  understand: 'Reviewing job requirements',
  check_result_count: 'Checking the number of matching jobs',
  recommend: 'Assessing job matches',
  present: 'Preparing your recommendations',
}
export function SearchLoading({ stage }: { stage: string }) {
  return (
    <section
      className="card min-h-96 items-center justify-center border border-base-300 bg-base-100 p-8 text-center"
      aria-live="polite"
    >
      <span className="mb-6 flex size-20 items-center justify-center rounded-full bg-primary/20 text-primary-content">
        <span className="loading loading-lg loading-spinner" />
      </span>
      <h2 className="text-xl font-semibold">{stages[stage] ?? 'Working on this step'}</h2>
      <p className="mt-3 max-w-sm text-sm leading-7 text-base-content/60">
        We’re organizing your search criteria and preparing job matches and application tips.
        <br />
        We’ll be ready to continue in a moment.
      </p>
      <p className="mt-6 text-xs text-base-content/40">
        This search may take a little while. Please wait.
      </p>
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
          <button className="btn rounded-xl border-0 btn-primary" onClick={onRetry}>
            Try again
            <Icon name="arrow" size={17} />
          </button>
        )}
        <button className="btn rounded-xl" onClick={onEdit}>
          Edit search criteria
        </button>
      </div>
    </section>
  )
}
