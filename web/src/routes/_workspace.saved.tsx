import { createFileRoute, useNavigate } from '@tanstack/react-router'
import { useEffect } from 'react'

import { PageHeading } from '../components/layout/page-heading'
import { Results } from '../components/results'
import { resultSearch } from '../lib/result-navigation'
import { useScout } from '../state/scout-context'
import { useSavedJobs } from '../state/workspace-queries'

export const Route = createFileRoute('/_workspace/saved')({
  validateSearch: resultSearch,
  component: SavedPage,
})

function SavedPage() {
  const saved = useScout((state) => state.saved)
  const toggleSaved = useScout((state) => state.toggleSaved)
  const query = useSavedJobs()
  const navigate = useNavigate()
  useEffect(() => {
    document.title = 'Saved jobs — JobScout'
  }, [])
  if (query.isPending)
    return (
      <output className="flex min-h-64 items-center justify-center gap-3">
        <span className="loading loading-sm loading-spinner" aria-hidden="true" />
        Loading saved jobs…
      </output>
    )
  return (
    <>
      <PageHeading
        title={
          query.data ? `${saved.length} ${saved.length === 1 ? 'job' : 'jobs'} saved` : 'Saved jobs'
        }
      />
      {query.data && (
        <Results
          result={null}
          saved={saved}
          savedOnly
          onToggle={toggleSaved}
          onEdit={() => {
            void navigate({ to: '/new' })
          }}
        />
      )}
    </>
  )
}
