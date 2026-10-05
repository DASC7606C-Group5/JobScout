import { createFileRoute, useNavigate } from '@tanstack/react-router'

import { PageHeading } from '../components/layout/page-heading'
import { Results } from '../components/results'
import { resultSearch } from '../lib/result-navigation'
import { useScout } from '../state/scout-context'

export const Route = createFileRoute('/_workspace/saved')({
  validateSearch: resultSearch,
  component: SavedPage,
})

function SavedPage() {
  const saved = useScout((state) => state.saved)
  const toggleSaved = useScout((state) => state.toggleSaved)
  const navigate = useNavigate()
  return (
    <>
      <PageHeading
        eyebrow="SAVED JOBS"
        title={`${saved.length} saved ${saved.length === 1 ? 'job' : 'jobs'}`}
        description="Compare the roles you saved during this visit."
      />
      <Results
        result={null}
        saved={saved}
        savedOnly
        onToggle={toggleSaved}
        onEdit={() => {
          void navigate({ to: '/', search: {} })
        }}
      />
    </>
  )
}
