import { createFileRoute } from '@tanstack/react-router'
import { useEffect } from 'react'

import { DiscoveryPage } from '../components/discovery/discovery-page'
import { rememberSessionId } from '../lib/session-storage'

export const Route = createFileRoute('/_workspace/new')({ component: NewSearch })

function NewSearch() {
  useEffect(() => {
    rememberSessionId(null)
    document.title = 'New search — JobScout'
  }, [])
  return <DiscoveryPage />
}
