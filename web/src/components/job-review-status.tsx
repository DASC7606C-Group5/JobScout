import type { RecommendationItem } from '../lib/contracts'
import { Icon } from './icon'

function reviewLabel(item: RecommendationItem, active: boolean) {
  if (active && item.review_status === 'reviewing') return 'Reviewing'
  if (active && item.review_status === 'queued') return 'Queued'
  if (item.review_status !== 'reviewed') return 'Unreviewed'
  if (item.analysis_status === 'unavailable') return 'Unavailable'
  if (item.analysis_status === 'partial') return 'Partial'
  return 'Reviewed'
}

export function JobReviewStatus({ item, active }: { item: RecommendationItem; active: boolean }) {
  const reviewing = active && item.review_status === 'reviewing'
  const queued = active && item.review_status === 'queued'
  const reviewed = item.review_status === 'reviewed'
  const label = reviewLabel(item, active)
  return (
    <span
      className={`badge h-auto min-h-7 gap-1.5 px-2.5 py-1 text-xs font-medium ${reviewing || queued ? 'border-warning/50 bg-warning/30 text-warning-content' : 'border-base-content/15 bg-base-100/70 text-base-content/75'}`}
    >
      {reviewing ? (
        <span className="loading loading-xs loading-ring" aria-hidden="true" />
      ) : (
        <Icon
          name={reviewed && item.analysis_status !== 'unavailable' ? 'check' : 'clock'}
          size={13}
        />
      )}
      {label}
    </span>
  )
}
