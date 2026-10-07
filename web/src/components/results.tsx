import { useMemo, useState } from 'react'

import { uniqueNotices } from '../lib/applicant-notices'
import type { ApplicantNotice, RecommendationItem, RecommendationResult } from '../lib/contracts'
import { generatedLabel } from '../lib/job-display'
import type { ResultSearch } from '../lib/result-navigation'
import { useTaskFeedback } from '../state/career-queries'
import { useResultSelection } from '../state/use-result-selection'
import { Icon } from './icon'
import { JobCard } from './job-card'
import { JobDetail } from './job-detail'
import { ResultEmpty } from './results/result-empty'
import { ResultFilters } from './results/result-filters'

type Selection = ReturnType<typeof useResultSelection>

export function Results({
  result,
  saved,
  onToggle,
  onEdit,
  savedOnly = false,
  notices = [],
  reviewActive = false,
}: {
  result: RecommendationResult | null
  saved: RecommendationItem[]
  onToggle: (item: RecommendationItem) => boolean | Promise<boolean> | void
  onEdit: () => void
  savedOnly?: boolean
  notices?: ApplicantNotice[]
  reviewActive?: boolean
}) {
  const feedback = useTaskFeedback(savedOnly ? undefined : result?.session_id)
  const [showDismissed, setShowDismissed] = useState(false)
  const jobs = useMemo(
    () =>
      savedOnly
        ? saved
        : [...(result?.jobs ?? []), ...(result?.pending_jobs ?? [])]
            .filter(
              (item) =>
                showDismissed ||
                !feedback.data?.some(
                  (entry) =>
                    entry.job_id === item.job.job_id && entry.interest === 'not_interested',
                ),
            )
            .sort(
              (left, right) =>
                Number(left.review_status !== 'reviewed') -
                Number(right.review_status !== 'reviewed'),
            ),
    [result, savedOnly, saved, feedback.data, showDismissed],
  )
  const selection = useResultSelection(jobs, savedOnly, onToggle)
  const jobNotices = uniqueNotices(
    [...(result ? result.notices : []), ...notices].filter((notice) => notice.scope === 'job'),
  )
  return (
    <section aria-label={savedOnly ? 'Saved jobs' : 'Recommended jobs'}>
      {!savedOnly && (
        <label className="label mb-4">
          <input
            className="checkbox"
            type="checkbox"
            checked={showDismissed}
            onChange={(event) => setShowDismissed(event.target.checked)}
          />
          Show dismissed jobs
        </label>
      )}
      <FilterControls jobs={jobs} selection={selection} />
      <ResultItems
        hasJobs={jobs.length > 0}
        savedOnly={savedOnly}
        saved={saved}
        selection={selection}
        onEdit={onEdit}
        notices={jobNotices}
        reviewActive={reviewActive}
        sessionId={savedOnly ? undefined : result?.session_id}
      />
      {!savedOnly && result && (
        <p className="mt-6 flex items-center gap-1.5 text-xs text-base-content/45">
          <Icon name="clock" size={13} />
          Updated {generatedLabel(result.generated_at)} · Hong Kong time
        </p>
      )}
    </section>
  )
}

function FilterControls({ jobs, selection }: { jobs: RecommendationItem[]; selection: Selection }) {
  if (!jobs.length) return null
  const { search, filtered, detailOpen, filterTo } = selection
  const directions = [
    'All',
    ...new Set(jobs.flatMap(({ job }) => [job.target_direction, ...job.target_directions])),
  ]
  return (
    <div className={detailOpen ? 'hidden min-[1100px]:block' : ''}>
      <ResultFilters
        directions={directions}
        direction={search.direction ?? 'All'}
        onDirectionChange={(direction) =>
          filterTo({ ...search, direction: direction === 'All' ? undefined : direction })
        }
        freshness={search.freshness ?? 'all'}
        onFreshnessChange={(freshness) =>
          filterTo({
            ...search,
            freshness: freshness === 'all' ? undefined : (freshness as ResultSearch['freshness']),
          })
        }
        count={jobs.length}
      />
      <p className="mb-4 text-xs text-base-content/55" aria-live="polite">
        Showing {filtered.length} {filtered.length === 1 ? 'job' : 'jobs'}
      </p>
    </div>
  )
}

function ResultItems({
  hasJobs,
  savedOnly,
  saved,
  selection,
  onEdit,
  notices,
  reviewActive,
  sessionId,
}: {
  hasJobs: boolean
  savedOnly: boolean
  saved: RecommendationItem[]
  selection: Selection
  onEdit: () => void
  notices: ApplicantNotice[]
  reviewActive: boolean
  sessionId?: string | undefined
}) {
  const {
    selected,
    filtered,
    detailOpen,
    buttons,
    detailHeading,
    changeSearch,
    selectJob,
    back,
    toggle,
  } = selection
  if (!hasJobs && !detailOpen) return <ResultEmpty savedOnly={savedOnly} onEdit={onEdit} />
  if (!selected)
    return (
      <div className="rounded-box border border-dashed border-base-300 py-12 text-center">
        <p className="text-sm text-base-content/65">No jobs match these filters.</p>
        <button className="btn mt-3 btn-ghost btn-sm" onClick={() => changeSearch({})}>
          Clear filters
        </button>
      </div>
    )
  return (
    <div className="grid items-start gap-6 min-[1100px]:grid-cols-[minmax(0,0.85fr)_minmax(0,1.15fr)]">
      <div className={`space-y-4 ${detailOpen ? 'hidden min-[1100px]:block' : ''}`}>
        {filtered.map((item) => (
          <JobCard
            key={item.job.job_id}
            item={item}
            reviewActive={reviewActive}
            selected={selected.job.job_id === item.job.job_id}
            saved={saved.some((entry) => entry.job.job_id === item.job.job_id)}
            onSelect={() => selectJob(item.job.job_id)}
            buttonRef={(node) => {
              if (node) buttons.current.set(item.job.job_id, node)
              else buttons.current.delete(item.job.job_id)
            }}
          />
        ))}
      </div>
      <div
        className={`min-w-0 min-[1100px]:sticky min-[1100px]:top-[var(--job-detail-top,1.5rem)] ${detailOpen ? '' : 'hidden min-[1100px]:block'}`}
      >
        {selection.outsideList && (
          <output className="mb-3 block text-sm text-base-content/65">
            You are viewing a job from an earlier version of your list.
          </output>
        )}
        <JobDetail
          key={selected.job.job_id}
          item={selected}
          tracking
          sessionId={sessionId}
          reviewActive={reviewActive}
          notices={notices}
          headingRef={detailHeading}
          saved={saved.some((entry) => entry.job.job_id === selected.job.job_id)}
          onToggle={() => {
            void toggle(selected)
          }}
          onBack={back}
        />
      </div>
    </div>
  )
}
