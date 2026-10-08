import { useMemo, type ReactNode } from 'react'

import { uniqueNotices } from '../lib/applicant-notices'
import type { ApplicantNotice, RecommendationItem, RecommendationResult } from '../lib/contracts'
import { generatedLabel } from '../lib/job-display'
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
  footerActions,
  onFeedback,
  feedbackPending = false,
  hiddenJobIds = [],
  resultOrder = [],
  feedbackByJob = {},
}: {
  result: RecommendationResult | null
  saved: RecommendationItem[]
  onToggle: (item: RecommendationItem) => boolean | Promise<boolean> | void
  onEdit: () => unknown
  savedOnly?: boolean
  notices?: ApplicantNotice[]
  reviewActive?: boolean
  footerActions?: ReactNode
  onFeedback?: (jobId: string, reaction: 'interested' | 'not_interested') => unknown
  feedbackPending?: boolean
  hiddenJobIds?: string[]
  resultOrder?: string[]
  feedbackByJob?: Record<string, 'interested' | 'not_interested'>
}) {
  const jobs = useMemo(() => {
    const hidden = new Set(hiddenJobIds)
    const order = new Map(resultOrder.map((id, index) => [id, index]))
    const source = savedOnly ? saved : [...(result?.jobs ?? []), ...(result?.pending_jobs ?? [])]
    return source
      .filter(({ job }) => savedOnly || !hidden.has(job.job_id))
      .sort((left, right) => {
        const leftOrder = order.get(left.job.job_id)
        const rightOrder = order.get(right.job.job_id)
        if (leftOrder !== undefined || rightOrder !== undefined)
          return (leftOrder ?? Number.MAX_SAFE_INTEGER) - (rightOrder ?? Number.MAX_SAFE_INTEGER)
        return (
          Number(left.review_status !== 'reviewed') - Number(right.review_status !== 'reviewed')
        )
      })
  }, [hiddenJobIds, result, resultOrder, savedOnly, saved])
  const selection = useResultSelection(jobs, savedOnly, onToggle)
  const jobNotices = uniqueNotices(
    [...(result ? result.notices : []), ...notices].filter((notice) => notice.scope === 'job'),
  )
  return (
    <section
      aria-label={savedOnly ? 'Saved jobs' : 'Recommended jobs'}
      className={jobs.length ? 'results-workspace' : undefined}
    >
      <FilterControls jobs={jobs} selection={selection} />
      <ResultItems
        hasJobs={jobs.length > 0}
        savedOnly={savedOnly}
        saved={saved}
        selection={selection}
        onEdit={onEdit}
        notices={jobNotices}
        reviewActive={reviewActive}
        {...(onFeedback ? { onFeedback } : {})}
        {...(feedbackPending ? { feedbackPending } : {})}
        feedbackByJob={feedbackByJob}
      />
      {((!savedOnly && result) || footerActions) && (
        <footer className="mt-3 flex shrink-0 flex-wrap items-center justify-between gap-x-6 gap-y-1 pt-2">
          {!savedOnly && result && (
            <p className="flex items-center gap-1.5 text-xs text-base-content/60">
              <Icon name="clock" size={13} />
              Updated {generatedLabel(result.generated_at)} · Hong Kong time
            </p>
          )}
          {footerActions && (
            <div className="flex flex-wrap items-center gap-1">{footerActions}</div>
          )}
        </footer>
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
        jobs={jobs}
        directions={directions}
        search={search}
        onChange={filterTo}
        filteredCount={filtered.length}
      />
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
  onFeedback,
  feedbackPending,
  feedbackByJob,
}: {
  hasJobs: boolean
  savedOnly: boolean
  saved: RecommendationItem[]
  selection: Selection
  onEdit: () => unknown
  notices: ApplicantNotice[]
  reviewActive: boolean
  onFeedback?: (jobId: string, reaction: 'interested' | 'not_interested') => unknown
  feedbackPending?: boolean
  feedbackByJob: Record<string, 'interested' | 'not_interested'>
}) {
  const {
    selected,
    filtered,
    detailOpen,
    buttons,
    detailHeading,
    detailScrollRef,
    rememberDetailScroll,
    selectJob,
    back,
    toggle,
  } = selection
  if (!hasJobs && !detailOpen) return <ResultEmpty savedOnly={savedOnly} onEdit={onEdit} />
  if (!selected)
    return (
      <div className="rounded-box border border-dashed border-base-300 py-12 text-center">
        <p className="text-sm text-base-content/65">No jobs match these filters.</p>
      </div>
    )
  return (
    <div className="grid min-h-0 flex-1 gap-4 min-[1100px]:grid-cols-[minmax(0,0.36fr)_minmax(0,0.64fr)]">
      <section
        aria-label="Job list"
        // oxlint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- Keyboard users must be able to scroll this independent pane.
        tabIndex={0}
        className={`min-h-0 min-w-0 space-y-3 min-[1100px]:[scrollbar-gutter:stable] min-[1100px]:overflow-y-auto min-[1100px]:overscroll-y-contain min-[1100px]:p-1 ${detailOpen ? 'hidden min-[1100px]:block' : ''}`}
      >
        {filtered.map((item) => (
          <JobCard
            key={item.job.job_id}
            item={item}
            reviewActive={reviewActive}
            {...(feedbackByJob[item.job.job_id]
              ? { feedback: feedbackByJob[item.job.job_id] }
              : {})}
            selected={selected.job.job_id === item.job.job_id}
            saved={saved.some((entry) => entry.job.job_id === item.job.job_id)}
            onSelect={() => selectJob(item.job.job_id)}
            buttonRef={(node) => {
              if (node) buttons.current.set(item.job.job_id, node)
              else buttons.current.delete(item.job.job_id)
            }}
          />
        ))}
      </section>
      <div
        className={`min-h-0 min-w-0 flex-col min-[1100px]:flex ${detailOpen ? 'flex' : 'hidden'}`}
      >
        {selection.outsideList && (
          <output className="mb-3 block text-sm text-base-content/65">
            You are viewing a job from an earlier version of your list.
          </output>
        )}
        <JobDetail
          key={selected.job.job_id}
          item={selected}
          notices={notices}
          reviewActive={reviewActive}
          headingRef={detailHeading}
          scrollRef={detailScrollRef}
          onScroll={rememberDetailScroll}
          saved={saved.some((entry) => entry.job.job_id === selected.job.job_id)}
          onToggle={() => toggle(selected)}
          onBack={back}
          {...(onFeedback
            ? {
                feedback: (reaction: 'interested' | 'not_interested') =>
                  onFeedback(selected.job.job_id, reaction),
              }
            : {})}
          {...(feedbackPending ? { feedbackPending } : {})}
          {...(feedbackByJob[selected.job.job_id]
            ? { reaction: feedbackByJob[selected.job.job_id] }
            : {})}
        />
      </div>
    </div>
  )
}
