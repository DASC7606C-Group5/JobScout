import { useCallback, useEffect, useState } from 'react'

import type { SearchActivity as Activity } from '../../lib/contracts'
import { fitLabels, statusTooltip } from '../../lib/job-status'
import { Icon } from '../icon'
import { StatusBadge } from '../status-badge'

function activityIcon(job: Activity) {
  if (job.status === 'found') return 'search'
  if (job.status === 'reviewing') return 'sparkles'
  if (job.status === 'reviewed') return 'check'
  if (job.status === 'excluded') return 'close'
  if (job.status === 'not_shortlisted') return 'arrow'
  return 'info'
}

const activityTones = {
  mint: { node: 'bg-primary/30 text-primary-content', label: 'text-primary-content' },
  pink: {
    node: 'bg-secondary/35 text-secondary-content',
    label: 'text-secondary-content',
  },
  amber: { node: 'bg-accent/40 text-accent-content', label: 'text-accent-content' },
  muted: { node: 'bg-base-200 text-base-content/65', label: 'text-base-content/65' },
}

function activityTone(job: Activity) {
  if (job.status === 'reviewing' || job.status === 'queued') return activityTones.pink
  if (
    job.status === 'unverified' ||
    ['partial', 'timeout', 'unavailable', 'invalid', 'insufficient', 'failed'].includes(
      job.status,
    ) ||
    (job.status === 'reviewed' && job.recommendation_fit === 'unlikely')
  )
    return activityTones.amber
  if (job.status === 'found' || job.status === 'reviewed') return activityTones.mint
  return activityTones.muted
}

function ActivityStatus({ job }: { job: Activity }) {
  return (
    <span className={`inline-flex flex-wrap items-center gap-1.5 ${activityTone(job).label}`}>
      <StatusBadge
        key={`${job.status}:${JSON.stringify(job.review_issue)}`}
        status={job.status}
        tooltip={statusTooltip(job.status, job)}
        appearance="text"
      />
      {['reviewed', 'partial', 'unverified', 'not_shortlisted'].includes(job.status) && (
        <span className="text-xs" aria-label={`Match: ${fitLabels[job.recommendation_fit]}`}>
          <span aria-hidden="true">· </span>
          {fitLabels[job.recommendation_fit]}
        </span>
      )}
    </span>
  )
}

function ActivityRow({
  job,
  index,
  paused,
  completed,
  onArchive,
}: {
  job: Activity
  index: number
  paused: boolean
  completed: boolean
  onArchive: (id: string, status: Activity['status']) => void
}) {
  const retire = ['excluded', 'expired', 'duplicate', 'not_shortlisted'].includes(job.status)
  useEffect(() => {
    if (!retire || paused) return
    const timer = window.setTimeout(() => onArchive(job.job_id, job.status), 3200)
    return () => window.clearTimeout(timer)
  }, [job.job_id, job.status, retire, paused, onArchive])
  const tone = activityTone(job)
  return (
    <li
      className="search-activity-enter"
      style={{ animationDelay: `${Math.min(index, 4) * 65}ms` }}
      data-job-id={job.job_id}
      data-status={job.status}
    >
      <div className={`search-activity-row ${retire && !paused ? 'search-activity-retire' : ''}`}>
        <div className="grid grid-cols-[1.75rem_minmax(0,1fr)] gap-2.5 sm:grid-cols-[2.125rem_minmax(0,1fr)] sm:gap-3.5">
          <div className="relative flex justify-center before:absolute before:top-10 before:bottom-0 before:w-px before:bg-base-300">
            <span
              className={`relative mt-4 flex size-7 shrink-0 items-center justify-center rounded-xl transition-colors duration-500 sm:size-8.5 ${tone.node}`}
            >
              <Icon
                key={job.status}
                name={activityIcon(job)}
                size={16}
                className={
                  job.status === 'reviewing' && !completed
                    ? 'search-review-icon'
                    : 'search-node-reveal'
                }
                style={job.status === 'reviewing' ? { animationDelay: `${index * -240}ms` } : {}}
              />
            </span>
          </div>
          <div
            className={`card min-w-0 border border-base-300 p-3.5 transition-colors duration-500 sm:p-4 ${retire ? 'bg-base-200/60' : job.status === 'reviewing' ? 'bg-secondary/5' : 'bg-base-100'}`}
          >
            <h3
              className={`text-sm font-semibold wrap-break-word sm:text-base ${job.status === 'excluded' ? 'search-activity-strike text-base-content/65' : ''}`}
            >
              {job.title}
            </h3>
            <p className="mt-1 text-xs text-base-content/65">
              {[job.company, job.location].filter(Boolean).join(' · ')}
            </p>
            <p
              key={`${job.status}:${job.recommendation_fit}`}
              className={`search-status-enter mt-3 flex items-center gap-1.5 text-xs font-medium ${tone.label}`}
            >
              <Icon name={activityIcon(job)} size={14} className="shrink-0" />
              <ActivityStatus job={job} />
            </p>
          </div>
        </div>
      </div>
    </li>
  )
}

export function SearchActivity({ jobs, completed }: { jobs: Activity[]; completed: boolean }) {
  const [archived, setArchived] = useState<Record<string, Activity['status']>>({})
  const [historyOpen, setHistoryOpen] = useState(false)
  const retire = useCallback((id: string, status: Activity['status']) => {
    setArchived((current) => ({ ...current, [id]: status }))
  }, [])
  const newest = [...jobs].reverse().sort((left, right) => right.sequence - left.sequence)
  const recent = newest.filter((job) => archived[job.job_id] !== job.status).slice(0, 5)
  const visibleIds = new Set(recent.map((job) => job.job_id))
  const history = newest.filter((job) => !visibleIds.has(job.job_id))
  return (
    <section aria-label="Job screening activity">
      {recent.length > 0 && (
        <div className="mb-3 flex items-center justify-between gap-3 pl-9.5 text-xs text-base-content/65 sm:pl-12">
          <span>{completed ? 'Screening activity' : 'Latest activity'}</span>
        </div>
      )}
      {recent.length ? (
        <ol
          className="space-y-3"
          aria-label="Recent jobs"
          aria-live="polite"
          aria-relevant="additions text"
        >
          {recent.map((job, index) => (
            <ActivityRow
              key={job.job_id}
              job={job}
              index={index}
              paused={historyOpen || completed}
              completed={completed}
              onArchive={retire}
            />
          ))}
        </ol>
      ) : (
        <p className="py-8 text-center text-sm text-base-content/65">
          {completed
            ? 'No further screening activity.'
            : history.length
              ? 'Looking for more matches…'
              : 'Searching for jobs that match your criteria…'}
        </p>
      )}
      {history.length > 0 && (
        <details
          className="group collapse mt-4 border border-base-300 bg-base-100"
          open={historyOpen}
          onToggle={(event) => setHistoryOpen(event.currentTarget.open)}
        >
          <summary className="collapse-title flex min-h-11 items-center justify-between gap-3 px-4 py-3 text-xs text-base-content/65">
            <span>Earlier activity ({history.length})</span>
            <Icon
              name="chevron"
              size={15}
              className="shrink-0 transition-transform group-open:rotate-90"
            />
          </summary>
          <div className="collapse-content">
            <ul className="space-y-4" aria-label="Earlier jobs">
              {history.map((job) => (
                <li
                  key={job.job_id}
                  className="flex gap-2.5 text-xs"
                  data-job-id={job.job_id}
                  data-status={job.status}
                >
                  <span className="mt-0.5 shrink-0 text-base-content/65">
                    <Icon name={activityIcon(job)} size={15} />
                  </span>
                  <div>
                    <p className="font-medium">{job.title}</p>
                    <p className="mt-1 text-base-content/65">
                      {job.company} · <ActivityStatus job={job} />
                    </p>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        </details>
      )}
    </section>
  )
}
