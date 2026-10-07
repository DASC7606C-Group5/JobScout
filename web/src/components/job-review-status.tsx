import type { RecommendationItem } from '../lib/contracts'
import { fitLabels, recommendationStatus, statusTooltip } from '../lib/job-status'
import { jobBadgeClass, StatusBadge } from './status-badge'

const fitColors: Record<RecommendationItem['recommendation_fit'], string> = {
  recommended: 'badge-success text-success-content',
  possible: 'badge-info text-info-content',
  unlikely: 'badge-warning text-warning-content',
  unknown: 'bg-base-200 text-base-content/75',
}

export function JobReviewStatus({ item, active }: { item: RecommendationItem; active: boolean }) {
  const status = recommendationStatus(item, active)
  const assessed = ['reviewed', 'summary_reviewed', 'partial', 'unverified'].includes(status)
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5">
      <StatusBadge
        key={`${status}:${JSON.stringify(item.review_issue)}`}
        status={status}
        tooltip={statusTooltip(status, item)}
      />
      {assessed && (
        <span
          className={`${jobBadgeClass} ${fitColors[item.recommendation_fit]}`}
          aria-label={`Match: ${fitLabels[item.recommendation_fit]}`}
        >
          {fitLabels[item.recommendation_fit]}
        </span>
      )}
    </span>
  )
}
