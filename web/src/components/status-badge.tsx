import { useEffect, useId, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

import { statusLabels, type JobStatus } from '../lib/job-status'

export const jobBadgeClass =
  'badge shrink-0 gap-1.5 border-0 badge-soft badge-sm font-medium select-none'

export function StatusBadge({
  status,
  tooltip,
  appearance = 'badge',
}: {
  status: JobStatus
  tooltip: string
  appearance?: 'badge' | 'text'
}) {
  const id = useId()
  const trigger = useRef<HTMLButtonElement>(null)
  const closing = useRef<ReturnType<typeof setTimeout> | null>(null)
  const [position, setPosition] = useState<{ left: number; top: number; above: boolean } | null>(
    null,
  )
  const busy = status === 'reviewing' || status === 'queued'
  const className =
    appearance === 'text'
      ? 'inline-flex items-center gap-1.5 text-xs font-medium text-current'
      : `${jobBadgeClass} ${busy ? 'badge-warning text-warning-content' : 'bg-base-200 text-base-content/75'}`
  function cancelClose() {
    if (closing.current) clearTimeout(closing.current)
  }
  function open() {
    cancelClose()
    const rect = trigger.current?.getBoundingClientRect()
    if (!rect) return
    const above = window.innerHeight - rect.bottom < 160 && rect.top > 160
    setPosition({
      left: Math.max(144, Math.min(window.innerWidth - 144, rect.left + rect.width / 2)),
      top: above ? rect.top : rect.bottom,
      above,
    })
  }
  function closeAfterHover() {
    cancelClose()
    closing.current = setTimeout(() => {
      if (document.activeElement !== trigger.current) setPosition(null)
    }, 120)
  }
  useEffect(() => {
    if (!position) return
    const dismiss = () => setPosition(null)
    const pointer = (event: PointerEvent) => {
      if (!trigger.current?.contains(event.target as Node)) dismiss()
    }
    const key = (event: KeyboardEvent) => {
      if (event.key === 'Escape') dismiss()
    }
    document.addEventListener('pointerdown', pointer)
    document.addEventListener('keydown', key)
    window.addEventListener('resize', dismiss)
    window.addEventListener('scroll', dismiss, true)
    return () => {
      document.removeEventListener('pointerdown', pointer)
      document.removeEventListener('keydown', key)
      window.removeEventListener('resize', dismiss)
      window.removeEventListener('scroll', dismiss, true)
    }
  }, [position])
  useEffect(
    () => () => {
      if (closing.current) clearTimeout(closing.current)
    },
    [],
  )
  const label = (
    <>
      {status === 'reviewing' && (
        <span className="loading loading-xs loading-ring" aria-hidden="true" />
      )}
      {statusLabels[status]}
    </>
  )
  if (!tooltip) return <span className={className}>{label}</span>
  return (
    <>
      <button
        ref={trigger}
        type="button"
        className={`${className} cursor-help focus-visible:outline-2 focus-visible:outline-offset-2`}
        aria-describedby={position ? id : undefined}
        onMouseEnter={open}
        onMouseLeave={closeAfterHover}
        onFocus={open}
        onBlur={() => setPosition(null)}
        onClick={open}
      >
        {label}
      </button>
      {position &&
        createPortal(
          <div
            className={`tooltip fixed z-50 tooltip-open ${position.above ? 'tooltip-top' : 'tooltip-bottom'}`}
            style={{ left: position.left, top: position.top }}
            onMouseEnter={cancelClose}
            onMouseLeave={closeAfterHover}
          >
            <div
              id={id}
              role="tooltip"
              className="tooltip-content pointer-events-auto w-64 max-w-[calc(100vw-6rem)] space-y-2 rounded-xl p-3 text-left text-xs leading-5 whitespace-normal"
            >
              <p className="font-semibold">{statusLabels[status]}</p>
              <p>{tooltip}</p>
            </div>
          </div>,
          document.body,
        )}
    </>
  )
}
