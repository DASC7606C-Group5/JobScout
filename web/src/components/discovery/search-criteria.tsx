import { useEffect, useId, useRef, useState, type CSSProperties } from 'react'

import type { UserProfile } from '../../lib/contracts'
import { summaryDraft, summaryFields } from '../../lib/search-summary'
import { AsyncButton } from '../async-button'
import { Icon } from '../icon'
import { SummaryValues } from '../profile/profile-summary'

export function SearchCriteria({
  profile,
  canEdit,
  onEdit,
}: {
  profile: UserProfile
  canEdit: boolean
  onEdit: () => unknown
}) {
  const id = useId().replace(/[^a-zA-Z0-9-]/g, '')
  const panelId = `search-criteria-${id}`
  const anchorName = `--${panelId}`
  const trigger = useRef<HTMLButtonElement>(null)
  const panel = useRef<HTMLElement>(null)
  const pinned = useRef(false)
  const closeTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const [open, setOpen] = useState(false)

  useEffect(() => () => clearTimeout(closeTimer.current), [])

  function cancelClose() {
    clearTimeout(closeTimer.current)
  }

  function closePreview() {
    cancelClose()
    if (pinned.current) return
    closeTimer.current = setTimeout(() => {
      if (!pinned.current) panel.current?.hidePopover()
    }, 180)
  }

  return (
    <section className="flex shrink-0 items-center gap-1 sm:gap-2" aria-label="Search criteria">
      <button
        ref={trigger}
        type="button"
        popoverTarget={panelId}
        aria-expanded={open}
        aria-controls={panelId}
        className="btn min-h-11 cursor-help gap-1.5 rounded-none border-0 bg-transparent px-2 font-normal text-base-content/65 shadow-none btn-sm hover:bg-transparent active:bg-transparent sm:min-h-0"
        style={{ anchorName } as CSSProperties}
        onPointerEnter={(event) => {
          if (event.pointerType !== 'mouse') return
          cancelClose()
          panel.current?.showPopover({ source: event.currentTarget })
        }}
        onPointerLeave={closePreview}
        onClick={(event) => {
          event.preventDefault()
          cancelClose()
          if (pinned.current) panel.current?.hidePopover()
          else {
            pinned.current = true
            panel.current?.showPopover({ source: event.currentTarget })
          }
        }}
      >
        <Icon name="info" size={16} />
        Search criteria
      </button>
      <AsyncButton
        type="button"
        className="btn min-h-11 btn-ghost px-2 btn-sm sm:min-h-0"
        disabled={!canEdit}
        onClick={() => {
          panel.current?.hidePopover()
          return onEdit()
        }}
      >
        Edit criteria
      </AsyncButton>
      {/* oxlint-disable-next-line jsx-a11y/no-noninteractive-element-interactions -- Pointer handlers keep the read-only preview open; the buttons provide keyboard and touch access. */}
      <section
        ref={panel}
        id={panelId}
        popover="auto"
        aria-label="Search criteria details"
        className="dropdown dropdown-center mt-2 max-h-[min(32rem,calc(100dvh-10rem))] w-lg max-w-[calc(100vw-2rem)] overflow-y-auto overscroll-contain rounded-box border border-base-300 bg-base-100 p-4 text-base-content shadow-lg sm:dropdown-end sm:max-h-[min(32rem,calc(100dvh-7rem))] sm:p-5"
        style={{ positionAnchor: anchorName } as CSSProperties}
        onMouseEnter={cancelClose}
        onMouseLeave={closePreview}
        onBeforeToggle={(event) => {
          if (event.newState === 'closed') {
            cancelClose()
            pinned.current = false
          }
        }}
        onToggle={(event) => setOpen(event.newState === 'open')}
      >
        <div className="mb-4 flex items-center justify-between gap-3">
          <h2 className="text-sm font-semibold">Search criteria</h2>
          <button
            type="button"
            aria-label="Close search criteria"
            popoverTarget={panelId}
            popoverTargetAction="hide"
            className="btn btn-circle size-11 btn-ghost text-base-content/60 btn-sm sm:size-8"
            onFocus={() => {
              cancelClose()
              pinned.current = true
            }}
          >
            <Icon name="close" size={16} />
          </button>
        </div>
        <SummaryValues
          fields={summaryFields.filter(
            ([key]) =>
              key === 'target_directions' ||
              key.startsWith('preferences.') ||
              key === 'search_options.result_count',
          )}
          draft={summaryDraft(profile)}
          profile={profile}
          collapseLongValues={false}
        />
      </section>
    </section>
  )
}
