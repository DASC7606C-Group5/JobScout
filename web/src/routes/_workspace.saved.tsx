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
  if (query.isError && !query.data)
    return (
      <div className="alert alert-error" role="alert">
        <span>
          Saved jobs could not be loaded. Your saved jobs are still kept in the workspace.
        </span>
        <button
          className="btn btn-sm"
          type="button"
          onClick={() => {
            void query.refetch()
          }}
        >
          Retry
        </button>
      </div>
    )
  return (
    <>
      <PageHeading
        eyebrow="SAVED JOBS"
        title={`${saved.length} ${saved.length === 1 ? 'job' : 'jobs'} saved`}
        description="Review and compare your saved jobs."
      />
      {query.isError && (
        <div className="mb-5 alert alert-warning" role="alert">
          <span>Saved jobs could not be refreshed. Showing the last loaded list.</span>
          <button
            className="btn btn-sm"
            type="button"
            onClick={() => {
              void query.refetch()
            }}
          >
            Retry
          </button>
        </div>
      )}
      <Results
        result={null}
        saved={saved}
        savedOnly
        onToggle={toggleSaved}
        onEdit={() => {
          void navigate({ to: '/new' })
        }}
      />
    </>
  )
}
