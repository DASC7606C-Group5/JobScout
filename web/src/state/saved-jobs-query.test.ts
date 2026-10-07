import { expect, test } from 'bun:test'

import { QueryClient, QueryObserver } from '@tanstack/react-query'

import { createRecommendationFixture } from '../../tests/fixtures'
import type { RecommendationItem } from '../lib/contracts'
import { createWorkspaceClient } from '../lib/workspace-client'
import { commitSavedJobs, savedJobsKey } from './workspace-queries'

test('a GET started during a saved-job write cannot restore a removed job after confirmation', async () => {
  const cache = new QueryClient()
  const removed = createRecommendationFixture()
  const retained = {
    ...createRecommendationFixture(),
    job: { ...removed.job, job_id: 'keep-job', title: 'Keep this supplied job' },
  }
  cache.setQueryData(savedJobsKey, [removed, retained])
  const requested = Promise.withResolvers<AbortSignal>()
  const staleResponse = Promise.withResolvers<Response>()
  const received = Promise.withResolvers<void>()
  const client = createWorkspaceClient('/api/v1', (_url, init) => {
    if (!init.signal) throw new Error('Expected a query cancellation signal')
    requested.resolve(init.signal)
    return staleResponse.promise
  })
  const observer = new QueryObserver(cache, {
    queryKey: savedJobsKey,
    queryFn: async ({ signal }) => {
      try {
        return await client.savedJobs(signal)
      } finally {
        received.resolve()
      }
    },
    staleTime: 0,
  })
  const unsubscribe = observer.subscribe(() => {})
  try {
    const signal = await requested.promise
    await commitSavedJobs(cache, (items) =>
      items.filter((item) => item.job.job_id !== removed.job.job_id),
    )
    expect(signal.aborted).toBe(true)
    staleResponse.resolve(Response.json({ items: [removed, retained] }))
    await received.promise
    expect(cache.getQueryData<RecommendationItem[]>(savedJobsKey)).toEqual([retained])
  } finally {
    unsubscribe()
    cache.clear()
  }
})
