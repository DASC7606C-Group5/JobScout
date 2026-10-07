import type { QueryClient } from '@tanstack/react-query'

import { identityEvents } from '../lib/auth-client'
import type { DraftResponse, WorkspaceClient } from '../lib/contracts'
import { DraftController } from './draft-controller'

let controllers = new WeakMap<QueryClient, Map<string, DraftController<object>>>()
const cached = new Set<DraftController<object>>()

identityEvents.addEventListener('change', () => {
  for (const controller of cached) controller.discard()
  cached.clear()
  controllers = new WeakMap()
})

export function getDraftController<T extends object>(
  cache: QueryClient,
  path: string,
  initial: T,
  client: WorkspaceClient,
) {
  let entries = controllers.get(cache)
  if (!entries) {
    entries = new Map()
    controllers.set(cache, entries)
  }
  const previous = entries.get(path)
  if (previous && !previous.isDiscarded()) return previous as unknown as DraftController<T>
  if (previous) cached.delete(previous)
  const controller = new DraftController<T>(
    initial,
    (request) =>
      client.saveDraft(path, {
        ...request,
        data: request.data as Record<string, unknown>,
      }) as Promise<DraftResponse<T>>,
    () => client.getDraft(path) as Promise<DraftResponse<T>>,
    (response) => cache.setQueryData(['draft', path], response),
  )
  entries.set(path, controller as unknown as DraftController<object>)
  cached.add(controller as unknown as DraftController<object>)
  return controller
}
