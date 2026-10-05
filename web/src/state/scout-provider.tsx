import { useQueryClient } from '@tanstack/react-query'
import { useRef, useState, type ReactNode } from 'react'

import type { SessionClient } from '../lib/contracts'
import { sessionClient } from '../lib/session-client'
import { workspaceClient } from '../lib/workspace-client'
import { ScoutContext } from './scout-context'
import { SessionContext } from './session-context'
import { useSessionWorkflow } from './use-session-workflow'
import { commitSavedJobs, savedJobsKey, useSavedJobs } from './workspace-queries'

export function ScoutProvider({
  children,
  client = sessionClient,
  sessionId = null,
  viewKey = '',
  onSessionCreated,
  onSessionDeleted,
}: {
  children: ReactNode
  client?: SessionClient
  sessionId?: string | null
  viewKey?: string
  onSessionCreated?: (id: string) => void
  onSessionDeleted?: (id: string) => void
}) {
  const cache = useQueryClient()
  const workflow = useSessionWorkflow(
    client,
    sessionId,
    viewKey,
    onSessionCreated,
    onSessionDeleted,
  )
  const savedQuery = useSavedJobs()
  const saved = savedQuery.data ?? []
  const [announcement, setAnnouncement] = useState('')
  const [saveError, setSaveError] = useState('')
  const saving = useRef(new Set<string>())
  async function toggleSaved(item: (typeof saved)[number]) {
    const id = item.job.job_id
    if (saving.current.has(id)) return false
    const exists = saved.some((entry) => entry.job.job_id === id)
    if (!exists && !workflow.session) return false
    saving.current.add(id)
    setSaveError('')
    let succeeded = false
    try {
      await cache.cancelQueries({ queryKey: savedJobsKey, exact: true })
      if (exists) {
        await workspaceClient.removeJob(id)
        await commitSavedJobs(cache, (previous) =>
          previous.filter((entry) => entry.job.job_id !== id),
        )
      } else {
        const confirmed = await workspaceClient.saveJob(
          id,
          workflow.session!.session_id,
          workflow.session!.revision,
        )
        await commitSavedJobs(cache, (previous) => [
          ...previous.filter((entry) => entry.job.job_id !== id),
          confirmed,
        ])
      }
      setAnnouncement(`${exists ? 'Removed from saved jobs' : 'Saved job'}: ${item.job.title}`)
      succeeded = true
    } catch (error) {
      const message =
        error instanceof Error ? error.message : 'Could not update saved jobs. Try again.'
      setAnnouncement(message)
      setSaveError(message)
    }
    saving.current.delete(id)
    return succeeded
  }
  return (
    <ScoutContext
      value={{
        saved,
        announcement,
        saveError,
        clearSaveError: () => setSaveError(''),
        toggleSaved,
      }}
    >
      <SessionContext value={workflow}>{children}</SessionContext>
    </ScoutContext>
  )
}
