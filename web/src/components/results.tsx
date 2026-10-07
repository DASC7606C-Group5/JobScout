import { useMemo, type ReactNode } from 'react'

import { uniqueNotices } from '../lib/applicant-notices'
import type { ApplicantNotice, RecommendationItem, RecommendationResult } from '../lib/contracts'
import { generatedLabel } from '../lib/job-display'
import type { ResultSearch } from '../lib/result-navigation'
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
}: {
  result: RecommendationResult | null
  saved: RecommendationItem[]
  onToggle: (item: RecommendationItem) => boolean | Promise<boolean> | void
  onEdit: () => unknown
  savedOnly?: boolean
  notices?: ApplicantNotice[]
  reviewActive?: boolean
  footerActions?: ReactNode
}) {
  const jobs = useMemo(
    () =>
      savedOnly
        ? saved
        : [...(result?.jobs ?? []), ...(result?.pending_jobs ?? [])].sort(
            (left, right) =>
              Number(left.review_status !== 'reviewed') -
              Number(right.review_status !== 'reviewed'),
          ),
    [result, savedOnly, saved],
  )
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
}: {
  hasJobs: boolean
  savedOnly: boolean
  saved: RecommendationItem[]
  selection: Selection
  onEdit: () => unknown
  notices: ApplicantNotice[]
  reviewActive: boolean
}) {
  const {
    selected,
    filtered,
    detailOpen,
    buttons,
    detailHeading,
    detailScrollRef,
    rememberDetailScroll,
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
        />
      </div>
    </div>
  )
}
