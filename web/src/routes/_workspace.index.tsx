import { createFileRoute } from '@tanstack/react-router'

import { DiscoveryPage } from '../components/discovery/discovery-page'

export const Route = createFileRoute('/_workspace/')({ component: DiscoveryPage })
