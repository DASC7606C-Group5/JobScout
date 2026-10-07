import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useSyncExternalStore } from 'react'

import type { DraftResponse } from '../lib/contracts'
import { workspaceClient } from '../lib/workspace-client'
import { registerDraft } from './draft-navigation'
import { getDraftController } from './draft-store'

export function usePersistedDraft<T extends object>(
  path: string,
  initial: T,
  client = workspaceClient,
) {
  const cache = useQueryClient()
  const controller = getDraftController(cache, path, initial, client)
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
