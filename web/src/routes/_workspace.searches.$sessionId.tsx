import { createFileRoute, Link } from '@tanstack/react-router'
import { useEffect } from 'react'

import { DiscoveryPage } from '../components/discovery/discovery-page'
import { PageHeading } from '../components/layout/page-heading'
import { resultSearch } from '../lib/result-navigation'
import { rememberSessionId } from '../lib/session-storage'
import { useScoutSession } from '../state/session-context'

export const Route = createFileRoute('/_workspace/searches/$sessionId')({
  validateSearch: resultSearch,
  component: SearchPage,
})

function SearchPage() {
  const { sessionId } = Route.useParams()
  const { session, error } = useScoutSession()
  useEffect(() => {
    rememberSessionId(sessionId)
    document.title = 'Search — JobScout'
  }, [sessionId])
  if (session) return <DiscoveryPage />
  if (error) {
    return (
      <section>
        <PageHeading title="Search" />
        <Link className="btn" to="/new">
          New search
        </Link>
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
