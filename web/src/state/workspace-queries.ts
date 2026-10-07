import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { InfiniteData, QueryClient } from '@tanstack/react-query'

import { SessionHttpError } from '../lib/api-client'
import type { RecommendationItem, SessionHistory } from '../lib/contracts'
import { sessionClient } from '../lib/session-client'
import { sessionKey } from '../lib/session-query'
import { workspaceClient } from '../lib/workspace-client'
import { discardSessionDrafts } from './draft-navigation'

export const historyKey = ['session-history'] as const
export const savedJobsKey = ['saved-jobs'] as const

export async function commitSavedJobs(
  cache: QueryClient,
  update: (items: RecommendationItem[]) => RecommendationItem[],
) {
  // A focus-triggered GET may have started while the write was pending.
  await cache.cancelQueries({ queryKey: savedJobsKey, exact: true })
  cache.setQueryData<RecommendationItem[]>(savedJobsKey, (previous = []) => update(previous))
}

export function useSessionHistory() {
  return useInfiniteQuery({
    queryKey: historyKey,
    queryFn: ({ pageParam, signal }) => workspaceClient.history(pageParam, signal),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
    refetchOnWindowFocus: true,
    staleTime: 0,
    retry: false,
  })
}

export function useSavedJobs() {
  return useQuery({
    queryKey: savedJobsKey,
    queryFn: ({ signal }) => workspaceClient.savedJobs(signal),
    retry: false,
    refetchOnWindowFocus: true,
  })
}

export function useDeleteSession() {
  const cache = useQueryClient()
  return useMutation({
    mutationFn: async (id: string) => {
      try {
        await sessionClient.delete(id)
      } catch (error) {
        if (!(error instanceof SessionHttpError && error.status === 404)) throw error
      }
    },
    onSuccess: (_data, id) => {
      cache.removeQueries({ queryKey: sessionKey(id), exact: true })
      discardSessionDrafts(id)
      cache.removeQueries({
        predicate: (query) =>
          query.queryKey[0] === 'draft' &&
          typeof query.queryKey[1] === 'string' &&
          query.queryKey[1].startsWith(`/sessions/${encodeURIComponent(id)}/drafts/`),
      })
      cache.setQueryData<InfiniteData<SessionHistory>>(
        historyKey,
        (previous) =>
          previous && {
            ...previous,
            pages: previous.pages.map((page) => ({
              ...page,
              items: page.items.filter((item) => item.session_id !== id),
            })),
          },
      )
      void cache.invalidateQueries({ queryKey: historyKey })
    },
  })
}
