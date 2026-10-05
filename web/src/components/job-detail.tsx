import type { RefObject } from 'react'

import { uniqueNotices } from '../lib/applicant-notices'
import type { ApplicantNotice, JobPosting, RecommendationItem } from '../lib/contracts'
import { dateLabel, safeSourceUrl, sourceLabel } from '../lib/job-display'
import { Icon } from './icon'
import { JobReviewStatus } from './job-review-status'
import { MatchingSourceQuotes } from './matching-source-quotes'
import { ResultWarnings } from './results/result-warnings'

export function JobDetail({
  item,
  saved,
  onToggle,
  onBack,
  notices,
  headingRef,
  reviewActive = false,
}: {
  item: RecommendationItem
  saved: boolean
  onToggle: () => void
  onBack: () => void
  notices: ApplicantNotice[]
  headingRef: RefObject<HTMLHeadingElement | null>
  reviewActive?: boolean
}) {
  const { job } = item
  const links = [...new Set([job.source_url, ...job.source_links])].flatMap((value) => {
    const url = safeSourceUrl(value)
    return url ? [url] : []
  })
  const jobNotices = uniqueNotices(
    [...notices, ...item.notices].filter(
      (notice) => notice.scope === 'job' && notice.job_id === job.job_id,
    ),
  )
  return (
    <article
      aria-label="Job details"
      className="card min-w-0 border border-base-300 bg-base-100 min-[1100px]:max-h-[calc(100dvh-var(--job-detail-top,1.5rem)-1.5rem)] min-[1100px]:scroll-pt-24 min-[1100px]:[scrollbar-gutter:stable] min-[1100px]:overflow-y-auto"
    >
      <div className="p-5 pb-0 sm:p-6 sm:pb-0">
        <button className="btn mb-5 btn-ghost btn-sm min-[1100px]:hidden" onClick={onBack}>
          <Icon name="arrow" size={15} className="rotate-180" />
          Back to jobs
        </button>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-sm text-base-content/65">{job.company}</p>
          <JobReviewStatus item={item} active={reviewActive} />
        </div>
        <h2
          ref={headingRef}
          tabIndex={-1}
          className="mt-2 text-2xl font-semibold tracking-tight break-words outline-none"
        >
          {job.title}
        </h2>
        <p className="mt-3 text-sm text-base-content/65">
          {[job.location, job.employment_type].filter(Boolean).join(' · ')}
        </p>
        <p className="mt-4 text-lg font-semibold">{job.salary || 'Salary not provided'}</p>
      </div>
      <div className="sticky top-0 z-10 flex flex-wrap gap-3 border-b border-base-300 bg-base-100 p-5 sm:p-6">
        {links[0] && (
          <a className="btn btn-primary" href={links[0]} target="_blank" rel="noopener noreferrer">
            View job listing <Icon name="external" size={16} />
          </a>
        )}
        <button
          className="btn"
          aria-label={`${saved ? 'Remove saved job' : 'Save job'}: ${job.title}`}
          aria-pressed={saved}
          onClick={onToggle}
        >
          <Icon name="bookmark" size={17} className={saved ? 'fill-secondary' : ''} />
          {saved ? 'Saved' : 'Save job'}
        </button>
      </div>
      <div className="space-y-6 p-5 text-sm leading-6 sm:p-6">
        <JobMatch item={item} />
        <Responsibilities job={job} />
        <Preparation item={item} />
        <ResultWarnings notices={jobNotices} listingUrl={links[0]} />
        <MatchingSourceQuotes reasons={item.matching_reasons} />
        <ListingMetadata job={job} links={links} />
      </div>
    </article>
  )
}

function JobMatch({ item }: { item: RecommendationItem }) {
  if (item.analysis_status === 'unavailable') return null
  const reasons = item.matching_reasons
    .filter((reason) => reason.level !== 'not_documented')
    .slice(0, 3)
  if (!reasons.length && !item.recommendation_reason) return null
  return (
    <section>
      <h3 className="mb-2 font-semibold">Why this role</h3>
      {item.recommendation_reason && (
        <p className="mb-3 text-base-content/75">{item.recommendation_reason}</p>
      )}
      <ul className="space-y-2 text-base-content/75">
        {reasons.map((reason) => (
          <li key={JSON.stringify(reason)}>{reason.explanation}</li>
        ))}
      </ul>
    </section>
  )
}

function Responsibilities({ job }: { job: JobPosting }) {
  if (job.responsibilities.length)
    return (
      <section>
        <h3 className="mb-2 font-semibold">What you’ll do</h3>
        <ul className="list-disc space-y-1 pl-4 text-base-content/75">
          {job.responsibilities.map((value) => (
            <li key={value}>{value}</li>
          ))}
        </ul>
      </section>
    )
  if (!job.description.trim()) return null
  return (
    <section>
      <h3 className="mb-2 font-semibold">About this role</h3>
      <p className="break-words whitespace-pre-wrap text-base-content/75">{job.description}</p>
    </section>
  )
}

function Preparation({ item }: { item: RecommendationItem }) {
  if (item.analysis_status === 'unavailable') return null
  const suggestions = [
    ...new Set(item.preparation_suggestions.filter((value) => value.trim())),
  ].slice(0, 2)
  if (!suggestions.length) return null
  return (
    <section>
      <h3 className="mb-2 font-semibold">Before you apply</h3>
      <ul className="list-disc space-y-1 pl-4 text-base-content/75">
        {suggestions.map((value) => (
          <li key={value}>{value}</li>
        ))}
      </ul>
    </section>
  )
}

function ListingMetadata({ job, links }: { job: JobPosting; links: string[] }) {
  return (
    <div className="border-t border-base-300 pt-4 text-xs text-base-content/60">
      <p>
        {sourceLabel(job.source)} · Retrieved {dateLabel(job.fetched_at)}
      </p>
      {job.posted_at && <p className="mt-1">Posted {dateLabel(job.posted_at)}</p>}
      {job.expiry_at && <p className="mt-1">Deadline {dateLabel(job.expiry_at)}</p>}
      {job.freshness_status === 'expired' && <p className="mt-2">This listing has expired.</p>}
      {links.slice(1).map((url, index) => (
        <a
          key={url}
          className="mt-2 mr-3 inline-flex link items-center gap-1"
          href={url}
          target="_blank"
          rel="noopener noreferrer"
        >
          Other source {index + 1}
          <Icon name="external" size={12} />
        </a>
      ))}
    </div>
  )
}
