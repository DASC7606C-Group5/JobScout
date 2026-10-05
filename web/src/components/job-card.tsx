import type { RecommendationItem } from '../lib/contracts'
import { Icon } from './icon'
import { JobReviewStatus } from './job-review-status'

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
      className={`card border ${selected ? 'border-secondary-content/35 bg-secondary/25' : 'border-secondary-content/15 bg-secondary/12'}`}
    >
      <button
        ref={buttonRef}
        type="button"
        aria-label={`View job: ${job.title}`}
        aria-pressed={selected}
        onClick={onSelect}
        className="w-full rounded-box p-5 text-left transition-colors hover:bg-secondary/10 sm:p-6"
      >
        <span className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <span className="text-xs text-base-content/75">{job.company}</span>
          <JobReviewStatus item={item} active={reviewActive} />
        </span>
        <h3 className="mt-1 text-lg font-semibold tracking-tight break-words">{job.title}</h3>
        <span className="mt-3 flex flex-wrap gap-x-3 gap-y-1 text-xs text-base-content/65">
          <span>{job.location}</span>
          {job.employment_type && <span>{job.employment_type}</span>}
          {job.freshness_status === 'expired' && <span>Expired</span>}
          {item.verification_status !== 'confirmed' && item.review_status === 'reviewed' && (
            <span>Details to check</span>
          )}
        </span>
        <span className="mt-4 block text-sm font-semibold">
          {job.salary || 'Salary not provided'}
        </span>
        {reason && (
          <span className="mt-3 block text-sm leading-6 text-base-content/70">{reason}</span>
        )}
        <span className="mt-4 flex items-center justify-between gap-3 text-xs">
          <span className="inline-flex items-center gap-1.5">
            View details <Icon name="arrow" size={14} />
          </span>
          {saved && (
            <span className="inline-flex items-center gap-1.5 text-base-content/60">
              <Icon name="bookmark" size={14} /> Saved
            </span>
          )}
        </span>
      </button>
    </article>
  )
}
