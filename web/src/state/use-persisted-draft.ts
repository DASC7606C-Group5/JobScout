import { useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { useEffect, useSyncExternalStore } from 'react'

import type { DraftResponse, WorkspaceClient } from '../lib/contracts'
import { workspaceClient } from '../lib/workspace-client'
import { DraftController } from './draft-controller'
import { registerDraft } from './draft-navigation'

const controllers = new WeakMap<QueryClient, Map<string, DraftController<object>>>()

function controllerFor<T extends object>(
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
  if (previous) return previous as unknown as DraftController<T>
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
  return controller
}

export function usePersistedDraft<T extends object>(
  path: string,
  initial: T,
  client = workspaceClient,
) {
  const cache = useQueryClient()
  const controller = controllerFor(cache, path, initial, client)
  const query = useQuery({
    queryKey: ['draft', path],
    queryFn: async ({ signal }) => {
      const response = (await client.getDraft(path, signal)) as DraftResponse<T>
      const confirmed = cache.getQueryData<DraftResponse<T>>(['draft', path])
      return confirmed && confirmed.revision > response.revision ? confirmed : response
    },
    staleTime: 0,
    retry: false,
    refetchOnWindowFocus: true,
  })
  const snapshot = useSyncExternalStore(
    controller.subscribe,
    controller.getSnapshot,
    controller.getSnapshot,
  )
  useEffect(() => {
    if (query.data) controller.hydrate(query.data)
    else if (query.error) controller.loadFailed(query.error)
  }, [controller, query.data, query.error])
  useEffect(() => registerDraft(controller, path), [controller, path])
  return {
    ...snapshot,
    setValue: controller.update,
    flush: controller.flush,
    retry: controller.retry,
    reload: controller.reload,
    overwrite: controller.overwrite,
    onCompositionStart: () => controller.setComposing(true),
    onCompositionEnd: () => controller.setComposing(false),
  }
}
