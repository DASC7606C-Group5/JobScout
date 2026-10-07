import { useSearch } from '@tanstack/react-router'
import { useState } from 'react'

import type { RecommendationItem, ScoutSession } from '../../lib/contracts'
import { searchPresentation } from '../../lib/search-presentation'
import { Icon } from '../icon'
import { Results } from '../results'
import { SearchActivity } from './search-activity'

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
  const active = !completed && !showResults
  const tone = !active
    ? { icon: 'bg-primary/30 text-primary-content', title: 'text-base-content' }
    : presentation.finishing
      ? { icon: 'bg-accent/40 text-accent-content', title: 'text-accent-content' }
      : presentation.comparing
        ? { icon: 'bg-secondary/35 text-secondary-content', title: 'text-secondary-content' }
        : { icon: 'bg-primary/30 text-primary-content', title: 'text-primary-content' }
  const hasResults = Boolean(
    session.recommendation?.jobs.length || session.recommendation?.pending_jobs.length,
  )
  function showMatches() {
    setSnapshot(session.recommendation)
    setView('results')
  }
  return (
    <>
      <section
        className={`card border border-base-300 bg-base-100 p-5 sm:p-7 ${showResults ? 'mb-6' : ''}`}
        aria-label="Search progress"
      >
        <div className="flex items-center gap-3.5" aria-live="polite">
          <span
            className={`relative flex size-12 shrink-0 items-center justify-center rounded-2xl transition-colors duration-500 ${tone.icon} ${active ? 'search-beacon' : ''}`}
          >
            <Icon
              name={
                completed
                  ? 'check'
                  : showResults
                    ? 'briefcase'
                    : presentation.comparing
                      ? 'sparkles'
                      : 'search'
              }
              size={23}
              className={
                active
                  ? presentation.comparing
                    ? 'search-review-icon'
                    : 'search-discover-icon'
                  : ''
              }
            />
          </span>
          <div
            key={`${completed}:${showResults}:${presentation.heading}`}
            className="search-status-enter min-w-0"
          >
            <h2 className={`text-xl font-semibold sm:text-2xl ${tone.title}`}>
              {completed
                ? showResults && hasResults
                  ? 'Your matches'
                  : 'Search complete'
                : showResults
                  ? 'Matches so far'
                  : presentation.heading}
            </h2>
            <p className="mt-1 text-xs text-base-content/65 sm:text-sm">
              {showResults && !completed
                ? 'The search is still running'
                : view === 'history'
                  ? 'How your matches were selected'
                  : presentation.activity}
            </p>
          </div>
        </div>
        {!showResults && (
          <div className="mt-7">
            <SearchActivity jobs={session.progress.activity} completed={completed} />
          </div>
        )}
        {(!completed || !showResults) && (
          <div className="mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-base-300 pt-4">
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              disabled={!hasResults && !showResults}
              onClick={showResults ? () => setView('activity') : showMatches}
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
        )}
      </section>
      {showResults && (
        <div className="search-results-enter">
          <Results
            result={completed ? session.recommendation : snapshot}
            saved={saved}
            onToggle={onToggle}
            onEdit={onEdit}
            notices={session.notices}
            reviewActive={!completed}
          />
          {completed && session.progress.activity.length > 0 && (
            <button
              type="button"
              className="btn mt-5 btn-ghost btn-sm"
              onClick={() => setView('history')}
            >
              <Icon name="clock" size={16} />
              View search activity
            </button>
          )}
        </div>
      )}
    </>
  )
}
