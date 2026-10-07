import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { careerClient } from '../../lib/career-client'
import { profileKey, useCurrentProfile } from '../../state/career-queries'
import { historyKey } from '../../state/workspace-queries'

export function TaskProfileControls({ sessionId }: { sessionId: string }) {
  const profile = useCurrentProfile()
  const cache = useQueryClient()
  const [title, setTitle] = useState('')
  const publish = useMutation({
    mutationFn: () => careerClient.importProfile(sessionId, profile.data?.revision ?? 0),
    onSuccess: (value) => cache.setQueryData(profileKey, value),
  })
  const rename = useMutation({
    mutationFn: () => careerClient.renameTask(sessionId, title),
    onSuccess: () => cache.invalidateQueries({ queryKey: historyKey }),
  })
  return (
    <div className="mb-5 space-y-3">
      <button
        className="btn btn-sm"
        disabled={publish.isPending || !profile.data}
        onClick={() => publish.mutate()}
      >
        Save this background as current profile
      </button>
      {publish.isSuccess && (
        <output>Current profile saved. Future task continuations use this revision.</output>
      )}
      {publish.isError && (
        <p role="alert">Profile could not be saved. Reload the current profile and try again.</p>
      )}
      <form
        onSubmit={(event) => {
          event.preventDefault()
          rename.mutate()
        }}
        className="flex flex-wrap items-center gap-2"
      >
        <label htmlFor="task-title">Task title</label>
        <input
          id="task-title"
          className="input"
          value={title}
          maxLength={200}
          required
          onChange={(event) => setTitle(event.target.value)}
        />
        <button className="btn btn-sm" disabled={rename.isPending}>
          Save title
        </button>
        {rename.isError && <p role="alert">Title could not be saved.</p>}
      </form>
    </div>
  )
}
