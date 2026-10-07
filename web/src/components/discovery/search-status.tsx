import { applicantErrorMessage } from '../../lib/applicant-errors'
import type { ApplicantError, ScoutSession } from '../../lib/contracts'
import { searchPresentation } from '../../lib/search-presentation'
import { Icon } from '../icon'

export function SearchLoading({ session }: { session: ScoutSession }) {
  const { heading, phase } = searchPresentation(session)
  return (
    <section
      className="card mb-6 border border-base-300 bg-base-100 p-5 sm:p-6"
      aria-label="Search progress"
    >
      <div className="flex items-center gap-4" aria-live="polite">
        <span className="loading loading-spinner text-primary-content" aria-hidden="true" />
        <div>
          <h2 className="text-lg font-semibold sm:text-xl">{heading}</h2>
          <p className="mt-1 text-sm text-base-content/65">
            {phase === 'profile'
              ? 'Checking your experience and preferences.'
              : 'Getting ready to find jobs.'}
          </p>
        </div>
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
