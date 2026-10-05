import { createFileRoute, Link } from '@tanstack/react-router'
import { useEffect } from 'react'

import { DiscoveryPage } from '../components/discovery/discovery-page'
import { applicantErrorMessage } from '../lib/applicant-errors'
import { resultSearch } from '../lib/result-navigation'
import { SessionHttpError } from '../lib/session-client'
import { rememberSessionId } from '../lib/session-storage'
import { useScoutSession } from '../state/session-context'

export const Route = createFileRoute('/_workspace/searches/$sessionId')({
  validateSearch: resultSearch,
  component: SearchPage,
})

function SearchPage() {
  const { sessionId } = Route.useParams()
  const { session, error, retry } = useScoutSession()
  useEffect(() => {
    rememberSessionId(sessionId)
    document.title = 'Search — JobScout'
  }, [sessionId])
  if (session) return <DiscoveryPage />
  if (error) {
    const missing = error instanceof SessionHttpError && error.status === 404
    return (
      <section
        className="card border border-base-300 bg-base-100 p-6"
        aria-labelledby="search-unavailable-title"
      >
        <h1 id="search-unavailable-title" className="text-xl font-semibold">
          {missing ? 'Search unavailable' : 'Could not load this search'}
        </h1>
        <p className="mt-3" role="alert">
          {applicantErrorMessage(missing ? 'search_not_found' : 'connection_unavailable')}
        </p>
        <div className="mt-5 flex gap-3">
          {!missing && (
            <button className="btn" onClick={retry}>
              Retry
            </button>
          )}
          <Link className="btn" to="/new">
            New search
          </Link>
        </div>
      </section>
    )
  }
  return (
    <output className="flex min-h-40 items-center gap-3" aria-live="polite">
      <span className="loading loading-spinner" aria-hidden="true" />
      Loading this search…
    </output>
  )
}
