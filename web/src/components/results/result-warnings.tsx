import { noticeIdentity, uniqueNotices } from '../../lib/applicant-notices'
import type { ApplicantNotice } from '../../lib/contracts'

export function ResultWarnings({
  notices,
  listingUrl,
  undocumented = [],
}: {
  notices: ApplicantNotice[]
  listingUrl?: string | undefined
  undocumented?: string[]
}) {
  const unique = uniqueNotices(notices)
  const missing = [...new Set(undocumented)].filter(
    (message) => !unique.some((notice) => notice.message === message),
  )
  if (!unique.length && !missing.length) return null
  const actions = new Set(unique.map((notice) => notice.action))
  const content = (
    <div className="text-sm leading-6 text-base-content/70">
      <ul className="space-y-3">
        {unique.map((notice) => (
          <li key={noticeIdentity(notice)}>{notice.message}</li>
        ))}
      </ul>
      {missing.length > 0 && (
        <div className={unique.length ? 'mt-3' : ''}>
          <h4 className="mb-2 text-xs font-medium">Details you haven't provided</h4>
          <ul className="space-y-2">
            {missing.map((message) => (
              <li key={message}>{message}</li>
            ))}
          </ul>
        </div>
      )}
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
      <h3 className="mb-2 font-semibold">Details to check</h3>
      {content}
    </aside>
  )
}
