import { createFileRoute } from '@tanstack/react-router'

import { DiscoveryPage } from '../components/discovery/discovery-page'
import { resultSearch } from '../lib/result-navigation'

export const Route = createFileRoute('/_workspace/')({
  validateSearch: resultSearch,
  component: DiscoveryPage,
})
