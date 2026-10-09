import { useId, useRef } from 'react'

import type { ScoutSession } from '../../lib/contracts'
import { Icon } from '../icon'
import { SourceOutcomes } from '../results/source-outcomes'

export function SearchRecord({ session, compact }: { session: ScoutSession; compact: boolean }) {
  const dialog = useRef<HTMLDialogElement>(null)
  const titleId = useId()
  const content = (
    <div className="space-y-5">
      <SourceOutcomes outcomes={session.source_outcomes} />
    </div>
  )
  if (!compact) return <div className="mt-6">{content}</div>
  if (!session.source_outcomes.length) return null
  return (
    <>
      <button
        type="button"
        className="btn gap-1.5 btn-ghost px-2 text-xs font-normal text-base-content/65 btn-sm"
        onClick={() => dialog.current?.showModal()}
      >
        <Icon name="info" size={15} />
        Search details
      </button>
      <dialog ref={dialog} className="modal" aria-labelledby={titleId}>
        <div className="modal-box w-11/12 max-w-3xl">
          <div className="mb-5 flex items-center justify-between gap-3">
            <h2 id={titleId} className="text-lg font-semibold">
              Search details
            </h2>
            <form method="dialog">
              <button type="submit" className="btn btn-ghost btn-sm">
                Close
              </button>
            </form>
          </div>
          {content}
        </div>
        <form method="dialog" className="modal-backdrop">
          <button type="submit">Close search details</button>
        </form>
      </dialog>
    </>
  )
}
