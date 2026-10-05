import { createFileRoute, useNavigate } from '@tanstack/react-router'

import { PageHeading } from '../components/layout/page-heading'
import { Results } from '../components/results'
import { useScout } from '../state/scout-context'

export const Route = createFileRoute('/_workspace/saved')({ component: SavedPage })

function SavedPage() {
  const saved = useScout((state) => state.saved)
  const toggleSaved = useScout((state) => state.toggleSaved)
  const navigate = useNavigate()
  return (
    <>
      <PageHeading
        eyebrow="KEEP THE POSSIBILITIES"
        title="Save jobs to compare later."
        description="Keep track of roles that interest you and get ready for your next step."
      />
      <Results
        result={null}
        saved={saved}
        savedOnly
        onToggle={toggleSaved}
        onEdit={() => {
          void navigate({ to: '/' })
        }}
      />
    </>
  )
}
