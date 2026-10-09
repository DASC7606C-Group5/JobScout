import { useSearch } from '@tanstack/react-router'
import { useState } from 'react'

import type { RecommendationItem, ScoutSession } from '../../lib/contracts'
import { searchPresentation } from '../../lib/search-presentation'
import { AsyncButton } from '../async-button'
import { Icon } from '../icon'
import { Results } from '../results'
import { SearchActivity } from './search-activity'
import { SearchRecord } from './search-record'

type SearchView = 'activity' | 'results' | 'history'

function initialView(session: ScoutSession, selectedJob: unknown): SearchView {
  const result = session.recommendation
  const hasSelectedJob = [...(result?.jobs ?? []), ...(result?.pending_jobs ?? [])].some(
    (item) => item.job.job_id === selectedJob,
  )
  return hasSelectedJob ||
    (session.outcome === 'completed' && result) ||
    (session.operation_kind === 'follow_up' && result) ||
    (session.outcome === 'failed' && result)
    ? 'results'
    : 'activity'
}

export function SearchExperience({
  session,
  onStop,
  stopping,
  saved,
  onToggle,
  onEdit,
  onRetry,
  onFeedback,
  feedbackDisabled = false,
}: {
  session: ScoutSession
  onStop: () => unknown
  stopping: boolean
  saved: RecommendationItem[]
  onToggle: (item: RecommendationItem) => boolean | Promise<boolean> | void
  onEdit: () => unknown
  onRetry: () => unknown
  onFeedback?: (jobId: string, reaction: 'interested' | 'not_interested' | null) => unknown
  feedbackDisabled?: boolean
}) {
  const search = useSearch({ strict: false })
  const [view, setView] = useState<SearchView>(() => initialView(session, search.job))
  const completed = session.outcome === 'completed'
  const settled = session.outcome !== 'running'
  const showResults = view === 'results' || (completed && view !== 'history')
  const presentation = searchPresentation(session)
  const hasResults = Boolean(
    session.recommendation?.jobs.length || session.recommendation?.pending_jobs.length,
  )
  function showMatches() {
    setView('results')
  }
  return (
    <>
      {(!completed || !showResults) && (
        <SearchProgress
          session={session}
          completed={completed}
          showResults={showResults}
          hasResults={hasResults}
          presentation={presentation}
          stopping={stopping}
          onStop={onStop}
          onView={showResults ? () => setView('activity') : showMatches}
          onEdit={onEdit}
          onRetry={onRetry}
        />
      )}
      {showResults && (
        <div className="results-layout">
          <SearchMatches
            session={session}
            result={session.recommendation}
            saved={saved}
            onToggle={onToggle}
            onEdit={onEdit}
            hasResults={hasResults}
            onViewActivity={() => setView('history')}
            {...(onFeedback ? { onFeedback } : {})}
            hiddenJobIds={session.hidden_job_ids}
            resultOrder={session.result_order}
            feedbackDisabled={feedbackDisabled}
          />
        </div>
      )}
      {settled && (!showResults || !hasResults) && (
        <div className="mt-3">
          <SearchRecord session={session} compact={hasResults} />
        </div>
      )}
    </>
  )
}

function SearchMatches({
  session,
  hasResults,
  onViewActivity,
  onFeedback,
  feedbackDisabled,
  ...props
}: {
  session: ScoutSession
  hasResults: boolean
  onViewActivity: () => void
  onFeedback?: (jobId: string, reaction: 'interested' | 'not_interested' | null) => unknown
  feedbackDisabled: boolean
  hiddenJobIds?: string[]
  resultOrder?: string[]
} & Pick<Parameters<typeof Results>[0], 'result' | 'saved' | 'onToggle' | 'onEdit'>) {
  const settled = session.outcome !== 'running'
  return (
    <Results
      {...props}
      notices={session.notices}
      reviewActive={!settled}
      feedbackDisabled={feedbackDisabled}
      {...(onFeedback ? { onFeedback } : {})}
      hiddenJobIds={session.hidden_job_ids}
      resultOrder={session.result_order}
      hiddenJobReasons={session.hidden_job_reasons}
      exclusions={session.result_preferences.exclusions}
      feedbackByJob={Object.fromEntries(
        session.job_feedback.map(({ job_id, reaction }) => [job_id, reaction]),
      )}
      footerActions={
        settled ? (
          <SearchResultActions
            session={session}
            hasResults={hasResults}
            onViewActivity={onViewActivity}
          />
        ) : undefined
      }
    />
  )
}

function SearchResultActions({
  session,
  hasResults,
  onViewActivity,
}: {
  session: ScoutSession
  hasResults: boolean
  onViewActivity: () => void
}) {
  return (
    <>
      {session.progress.activity.length > 0 && (
        <button
          type="button"
          className="btn gap-1.5 btn-ghost px-2 text-xs font-normal text-base-content/65 btn-sm"
          onClick={onViewActivity}
        >
          <Icon name="clock" size={15} />
          View search activity
        </button>
      )}
      {hasResults && <SearchRecord session={session} compact />}
    </>
  )
}

type SearchProgressProps = {
  session: ScoutSession
  completed: boolean
  showResults: boolean
  hasResults: boolean
  presentation: ReturnType<typeof searchPresentation>
  stopping: boolean
  onStop: () => unknown
  onView: () => void
  onEdit: () => unknown
  onRetry: () => unknown
}

function SearchProgress(props: SearchProgressProps) {
  const { session, completed, showResults, presentation } = props
  return (
    <section
      aria-label="Search progress"
      className={showResults ? 'mb-4' : 'card border border-base-300 bg-base-100 p-5 sm:p-6'}
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <SearchPhaseIndicator completed={completed} presentation={presentation} />
        <SearchProgressActions {...props} />
      </div>
      {!showResults && (
        <div className="mt-5 sm:mt-6">
          <SearchActivity
            jobs={session.progress.activity}
            completed={session.outcome !== 'running'}
          />
        </div>
      )}
    </section>
  )
}

function SearchProgressActions({
  session,
  showResults,
  hasResults,
  presentation,
  stopping,
  onStop,
  onView,
  onEdit,
  onRetry,
}: SearchProgressProps) {
  const finishing = stopping || presentation.finishing
  return (
    <div className="ml-auto flex flex-wrap items-center justify-end gap-2">
      <button
        type="button"
        className="btn btn-ghost btn-sm"
        disabled={!hasResults && !showResults}
        onClick={onView}
      >
        {showResults && <Icon name="arrow" className="rotate-180" size={16} />}
        {showResults
          ? 'Back to search'
          : session.outcome !== 'running'
            ? 'View jobs'
            : 'View jobs so far'}
        {!showResults && <Icon name="arrow" size={16} />}
      </button>
      {(presentation.canFinish || presentation.finishing) && (
        <AsyncButton
          type="button"
          className="btn btn-sm"
          disabled={finishing}
          pending={finishing}
          onClick={onStop}
        >
          {finishing ? 'Finishing…' : 'Finish search'}
        </AsyncButton>
      )}
      {presentation.interrupted && (
        <>
          {session.retryable && (
            <AsyncButton type="button" className="btn btn-sm" onClick={onRetry}>
              Try again
            </AsyncButton>
          )}
          <AsyncButton type="button" className="btn btn-ghost btn-sm" onClick={onEdit}>
            Edit search criteria
          </AsyncButton>
        </>
      )}
    </div>
  )
}

function SearchPhaseIndicator({
  completed,
  presentation,
}: {
  completed: boolean
  presentation: ReturnType<typeof searchPresentation>
}) {
  return (
    <output className="flex items-center gap-3 text-sm text-base-content/75">
      {presentation.interrupted ? (
        <span className="flex size-8 shrink-0 items-center justify-center rounded-xl bg-base-200 text-base-content/65">
          <Icon name="info" size={17} />
        </span>
      ) : completed ? (
        <span className="flex size-8 shrink-0 items-center justify-center rounded-xl bg-primary/30 text-primary-content">
          <Icon name="check" size={17} />
        </span>
      ) : (
        <span
          className={`search-beacon relative flex size-8 shrink-0 items-center justify-center rounded-xl ${presentation.comparing ? 'bg-secondary/35 text-secondary-content' : 'bg-primary/30 text-primary-content'}`}
        >
          <Icon
            name={presentation.comparing ? 'sparkles' : 'search'}
            size={17}
            className={presentation.comparing ? 'search-review-icon' : 'search-discover-icon'}
          />
        </span>
      )}
      <span>{completed ? 'How these jobs were reviewed' : presentation.activity}</span>
    </output>
  )
}
