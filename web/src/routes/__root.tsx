import type { QueryClient } from '@tanstack/react-query'
import { createRootRouteWithContext, Link, Outlet } from '@tanstack/react-router'

import { AccountObserver } from '../components/account-observer'
import { NotificationProvider } from '../components/notifications'

interface RouterContext {
  queryClient: QueryClient
}

export const Route = createRootRouteWithContext<RouterContext>()({
  component: RootLayout,
  notFoundComponent: NotFound,
})

function RootLayout() {
  return (
    <NotificationProvider>
      <AccountObserver />
      <Outlet />
    </NotificationProvider>
  )
}

function NotFound() {
  return (
    <main className="mx-auto max-w-xl px-6 py-20">
      <h1 className="text-3xl font-semibold">Page not found</h1>
      <p className="mt-3 mb-6">Return to the home page to keep exploring opportunities.</p>
      <Link to="/" className="btn">
        Back to JobScout
      </Link>
    </main>
  )
}
