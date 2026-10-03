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
        title="心动的机会，慢慢比较。"
        description="留住值得关注的岗位，为下一步做好准备。"
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
