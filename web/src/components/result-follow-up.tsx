import { useState } from 'react'

import type { FollowUpRequest, FollowUpSubmission } from '../lib/contracts'
import { useScoutSession } from '../state/session-context'
import { Icon } from './icon'

export function ResultFollowUp({ jobId }: { jobId?: string | null }) {
  const { followUp, busy, pending } = useScoutSession()
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const submit = (action: FollowUpRequest['action']) => {
    const text = message.trim()
    if (action === 'message' && !text) {
      setError('Write a question or preference before sending.')
      return
    }
    setError('')
    const request: FollowUpSubmission =
      action === 'message'
        ? { action, job_id: jobId ?? null, message: text }
        : { action: 'find_similar', job_id: jobId ?? '' }
    void followUp(request).then((submitted) => {
      if (submitted) setMessage('')
    })
  }
  return (
    <section
      className="card border border-base-300 bg-base-100 p-4 sm:p-5"
      aria-label="Continue the conversation"
    >
      <h2 className="text-sm font-semibold">Continue with these results</h2>
      <p className="mt-1 text-sm text-base-content/65">
        Ask for a change or find roles similar to the selected job.
      </p>
      <textarea
        className="textarea mt-3 min-h-24 w-full border border-base-300 bg-base-200/25 text-base leading-6 sm:text-sm"
        value={message}
        onChange={(event) => setMessage(event.target.value)}
        maxLength={10000}
        disabled={busy}
        placeholder="For example: show more roles with flexible hours"
      />
      {error && (
        <p className="mt-2 text-sm text-error" role="alert">
          {error}
        </p>
      )}
      <div className="mt-3 flex flex-wrap justify-end gap-2">
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          disabled={busy || pending || !jobId}
          onClick={() => submit('find_similar')}
        >
          Find similar
        </button>
        <button
          type="button"
          className="btn btn-primary btn-sm"
          disabled={busy || pending}
          onClick={() => submit('message')}
        >
          {pending && <span className="loading loading-xs loading-spinner" aria-hidden="true" />}
          Send <Icon name="arrow" size={15} />
        </button>
      </div>
    </section>
  )
}
