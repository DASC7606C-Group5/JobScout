import { useSearch } from '@tanstack/react-router'
import { useState } from 'react'

import type { RecommendationItem, ScoutSession } from '../../lib/contracts'
import { searchPresentation } from '../../lib/search-presentation'
import { Icon } from '../icon'
import { Results } from '../results'
import { SearchActivity } from './search-activity'
import { SearchRecord } from './search-record'

export function SearchExperience({
  session,
  onStop,
  stopping,
  saved,
  onToggle,
  onEdit,
}: {
  session: ScoutSession
  onStop: () => void
  stopping: boolean
  saved: RecommendationItem[]
  onToggle: (item: RecommendationItem) => boolean | Promise<boolean> | void
  onEdit: () => void
}) {
  const search = useSearch({ strict: false })
  const [view, setView] = useState<'activity' | 'results' | 'history'>(
    search.job ? 'results' : 'activity',
  )
  const [snapshot, setSnapshot] = useState(session.recommendation)
  const completed = session.outcome === 'completed'
  const showResults = view === 'results' || (completed && view !== 'history')
  const presentation = searchPresentation(session)
  const hasResults = Boolean(
    session.recommendation?.jobs.length || session.recommendation?.pending_jobs.length,
  )
  function showMatches() {
    setSnapshot(session.recommendation)
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
        />
      )}
      {showResults && (
        <div className="results-layout search-results-enter">
          <Results
            result={completed ? session.recommendation : snapshot}
            saved={saved}
            onToggle={onToggle}
            onEdit={onEdit}
            notices={session.notices}
            reviewActive={!completed}
            footerActions={
              completed ? (
                <SearchResultActions
                  session={session}
                  hasResults={hasResults}
                  onViewActivity={() => setView('history')}
                />
              ) : undefined
            }
          />
        </div>
      )}
      {completed && (!showResults || !hasResults) && (
        <div className="mt-3">
          <SearchRecord session={session} compact={hasResults} />
        </div>
      )}
    </>
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

function SearchProgress({
  session,
  completed,
  showResults,
  hasResults,
  presentation,
  stopping,
  onStop,
  onView,
}: {
  session: ScoutSession
  completed: boolean
  showResults: boolean
  hasResults: boolean
  presentation: ReturnType<typeof searchPresentation>
  stopping: boolean
  onStop: () => void
  onView: () => void
}) {
  return (
    <section
      aria-label="Search progress"
      className={
        showResults
          ? 'mb-4 flex flex-wrap items-center justify-between gap-3'
          : 'card border border-base-300 bg-base-100 p-5 sm:p-6'
      }
    >
      <SearchPhaseIndicator completed={completed} presentation={presentation} />
      {!showResults && (
        <div className="mt-5 sm:mt-6">
          <SearchActivity jobs={session.progress.activity} completed={completed} />
        </div>
      )}
      <div
        className={`flex flex-wrap items-center justify-between gap-2 ${showResults ? '' : '-mx-5 mt-5 border-t border-base-300 px-5 pt-5 sm:-mx-6 sm:mt-6 sm:px-6 sm:pt-6'}`}
      >
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          disabled={!hasResults && !showResults}
          onClick={onView}
        >
          {showResults && <Icon name="arrow" className="rotate-180" size={16} />}
          {showResults ? 'Back to search' : completed ? 'View matches' : 'View matches so far'}
          {!showResults && <Icon name="arrow" size={16} />}
        </button>
        {(presentation.canFinish || presentation.finishing) && (
          <button
            type="button"
            className="btn btn-sm"
            disabled={stopping || presentation.finishing}
            aria-busy={stopping || presentation.finishing}
            onClick={onStop}
          >
            {stopping || presentation.finishing ? 'Finishing…' : 'Finish search'}
          </button>
        )}
      </div>
    </section>
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
      {completed ? (
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
      <span>{completed ? 'How your matches were selected' : presentation.activity}</span>
    </output>
  )
}
