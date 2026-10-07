import type { RecommendationItem } from '../lib/contracts'
import { Icon } from './icon'
import { JobReviewStatus } from './job-review-status'
import { MatchScoreSummary } from './match-score'

export function JobCard({
  item,
  selected,
  saved,
  onSelect,
  buttonRef,
  reviewActive = false,
}: {
  item: RecommendationItem
  selected: boolean
  saved: boolean
  onSelect: () => void
  buttonRef: (node: HTMLButtonElement | null) => void
  reviewActive?: boolean
}) {
  const { job } = item
  const reason =
    item.analysis_status !== 'unavailable'
      ? item.matching_reasons.find((entry) => entry.level !== 'not_documented')?.explanation
      : null
  return (
    <article
      className={`card border ${selected ? 'border-secondary-content/35 bg-secondary/20' : 'border-base-300 bg-base-100'}`}
    >
      <button
        ref={buttonRef}
        type="button"
        aria-label={`View job: ${job.title}`}
        aria-pressed={selected}
        onClick={onSelect}
        className="w-full rounded-box p-4 text-left transition-colors hover:bg-secondary/10"
      >
        <span className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <span className="text-xs text-base-content/75">{job.company}</span>
          <JobReviewStatus item={item} active={reviewActive} />
        </span>
        <h3 className="text-base font-semibold tracking-tight wrap-anywhere">{job.title}</h3>
        <span className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-base-content/65">
          <span>{job.location}</span>
          {job.employment_type && <span>{job.employment_type}</span>}
          {job.freshness_status === 'expired' && <span>Expired</span>}
          {item.verification_status !== 'confirmed' && item.review_status === 'reviewed' && (
            <span>Details to check</span>
          )}
        </span>
        <span className="mt-2 block text-sm font-semibold">
          {job.salary || 'Salary not provided'}
        </span>
        {reason && (
          <span className="mt-2 line-clamp-2 text-sm leading-6 text-base-content/70">{reason}</span>
        )}
        <MatchScoreSummary score={item.match_score} />
        {saved && (
          <span className="mt-2 inline-flex items-center gap-1.5 text-xs text-base-content/60">
            <Icon name="bookmark" size={14} /> Saved
          </span>
        )}
      </button>
    </article>
  )
}
