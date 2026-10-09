import { useEffect, useState } from 'react'

import type { ScoutSession } from '../../lib/contracts'
import { AsyncButton } from '../async-button'

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
    <section className="card bg-base-100 card-border" aria-label="Waiting request">
      <div className="card-body gap-4 p-5 sm:p-6">
        <h2 className="card-title" aria-live="polite">
          Your place in line: {session.queue_position}
        </h2>
        <p>{minutes === 0 ? 'Just joined' : `Waiting for ${minutes} min`}</p>
        {session.expires_at && (
          <p className="text-sm text-base-content/70">
            Expires at{' '}
            <time dateTime={session.expires_at}>
              {new Date(session.expires_at).toLocaleString()}
            </time>
          </p>
        )}
        <p className="text-sm">You can close this page and come back later.</p>
        <div className="card-actions">
          <AsyncButton
            type="button"
            className="btn"
            aria-label="Cancel request"
            pending={cancelling}
            onClick={onCancel}
          >
            {cancelling ? 'Cancelling…' : 'Cancel request'}
          </AsyncButton>
        </div>
      </div>
    </section>
  )
}
