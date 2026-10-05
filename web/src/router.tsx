import { createRouter } from '@tanstack/react-router'

import { queryClient } from './lib/query-client'
import { routeTree } from './routeTree.gen'

export const router = createRouter({
  routeTree,
  context: { queryClient },
  scrollRestoration: false,
  defaultPreload: 'intent',
  defaultPreloadStaleTime: 0,
  defaultViewTransition: {
    types: ({ fromLocation, toLocation }) =>
      fromLocation && fromLocation.pathname !== toLocation.pathname ? ['page'] : false,
  },
})

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
}
