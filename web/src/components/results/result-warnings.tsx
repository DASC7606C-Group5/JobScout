import { noticeIdentity, uniqueNotices } from '../../lib/applicant-notices'
import type { ApplicantNotice } from '../../lib/contracts'

export function ResultWarnings({
  notices,
  onEdit,
  onRetry,
  listingUrl,
  collapsed = false,
}: {
  notices: ApplicantNotice[]
  onEdit?: () => void
  onRetry?: () => void
  listingUrl?: string | undefined
  collapsed?: boolean
}) {
  const unique = uniqueNotices(notices)
  if (!unique.length) return null
  const actions = new Set(unique.map((notice) => notice.action))
  const content = (
    <div className="text-sm leading-6 text-base-content/70">
      <ul className="space-y-3">
        {unique.map((notice) => (
          <li key={noticeIdentity(notice)}>{notice.message}</li>
        ))}
      </ul>
      <div className="mt-2 flex flex-wrap gap-2">
        {actions.has('edit_conditions') && onEdit && (
          <button className="btn btn-ghost btn-sm" onClick={onEdit}>
            Edit search criteria
          </button>
        )}
        {actions.has('retry') && onRetry && (
          <button className="btn btn-ghost btn-sm" onClick={onRetry}>
            Try again
          </button>
        )}
        {actions.has('open_listing') && listingUrl && (
          <a className="link" href={listingUrl} target="_blank" rel="noopener noreferrer">
            View full listing
          </a>
        )}
      </div>
    </div>
  )
  return collapsed ? (
    <details className="collapse-arrow collapse border border-base-300 bg-base-100">
      <summary className="collapse-title text-sm font-medium">About this search</summary>
      <div className="collapse-content">{content}</div>
    </details>
  ) : (
    <aside aria-label="Important details" className="rounded-box bg-base-200/60 p-4">
      {content}
    </aside>
  )
}
