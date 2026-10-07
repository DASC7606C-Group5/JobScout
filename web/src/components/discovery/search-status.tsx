import type { ScoutSession } from '../../lib/contracts'
import { searchPresentation } from '../../lib/search-presentation'

export function SearchLoading({ session }: { session: ScoutSession }) {
  const { phase } = searchPresentation(session)
  return (
    <section className="mb-5 py-3" aria-label="Search progress">
      <div className="flex items-center gap-4" aria-live="polite">
        <span className="loading loading-spinner text-primary-content" aria-hidden="true" />
        <div>
          <p className="text-sm text-base-content/65">
            {phase === 'profile'
              ? 'Checking your experience and preferences.'
              : 'Getting ready to find jobs.'}
          </p>
        </div>
      </div>
    </section>
  )
}
