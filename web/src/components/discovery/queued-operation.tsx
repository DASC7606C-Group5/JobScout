import { useEffect, useState } from 'react'

import type { ScoutSession } from '../../lib/contracts'
import { AsyncButton } from '../async-button'
import { Icon } from '../icon'

export function QueuedOperation({
  session,
  onCancel,
  cancelling,
}: {
  session: ScoutSession
  onCancel: () => unknown
  cancelling: boolean
}) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 10_000)
    return () => window.clearInterval(timer)
  }, [])
  const minutes = session.enqueued_at
    ? Math.max(0, Math.floor((now - Date.parse(session.enqueued_at)) / 60_000))
    : 0
  return (
    <section className="card border border-base-300 bg-base-100 p-4" aria-label="Queued operation">
      <div className="flex flex-wrap items-center gap-3 sm:flex-nowrap">
        <Icon name="clock" size={20} className="shrink-0 text-base-content/65" />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-x-2">
            <h2 className="text-sm font-semibold" aria-live="polite">
              Queue position {session.queue_position}
            </h2>
            <span className="text-xs text-base-content/65">Waiting {minutes} min</span>
          </div>
          <p className="mt-1 text-xs text-base-content/65">
            Request saved. You can close this page.
          </p>
        </div>
        <AsyncButton
          type="button"
          className="btn btn-ghost btn-sm"
          aria-label="Cancel queued request"
          pending={cancelling}
          onClick={onCancel}
        >
          {cancelling ? 'Cancelling…' : 'Cancel'}
        </AsyncButton>
      </div>
      {session.expires_at && (
        <p className="mt-3 text-xs text-base-content/65">
          Expires at{' '}
          <time dateTime={session.expires_at}>{new Date(session.expires_at).toLocaleString()}</time>
          .
        </p>
      )}
    </section>
  )
}
