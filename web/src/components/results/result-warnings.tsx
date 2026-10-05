import { noticeIdentity, uniqueNotices } from '../../lib/applicant-notices'
import type { ApplicantNotice } from '../../lib/contracts'

export function ResultWarnings({
  notices,
  listingUrl,
}: {
  notices: ApplicantNotice[]
  listingUrl?: string | undefined
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
        {actions.has('open_listing') && listingUrl && (
          <a className="link" href={listingUrl} target="_blank" rel="noopener noreferrer">
            View full listing
          </a>
        )}
      </div>
    </div>
  )
  return (
    <aside aria-label="Important details" className="rounded-box bg-base-200/60 p-4">
      {content}
    </aside>
  )
}
