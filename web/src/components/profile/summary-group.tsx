import { useId, useState, type ReactNode } from 'react'

export function SummaryGroup({
  title,
  changed,
  needsAttention,
  summary,
  children,
  editable = true,
}: {
  title: string
  changed: boolean
  needsAttention: boolean
  summary: ReactNode
  children: ReactNode
  editable?: boolean
}) {
  const id = useId()
  const [expanded, setExpanded] = useState<boolean | null>(null)
  const editing = needsAttention || (expanded ?? changed)
  return (
    <section className="-mx-5 min-w-0 border-b border-base-300 px-5 pb-5 last:border-0 sm:-mx-6 sm:px-6 sm:pb-6">
      <div className="mb-3 flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold">{title}</h2>
        {editable && (
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            aria-expanded={editing}
            aria-controls={id}
            aria-label={
              editing ? `Close ${title.toLowerCase()} editor` : `Edit ${title.toLowerCase()}`
            }
            disabled={needsAttention}
            onClick={() => setExpanded(!editing)}
          >
            {editing ? 'Close' : 'Edit'}
          </button>
        )}
      </div>
      {editing ? <div id={id}>{children}</div> : <div id={id}>{summary}</div>}
    </section>
  )
}
