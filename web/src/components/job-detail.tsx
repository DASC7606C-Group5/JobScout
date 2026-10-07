import type { Ref, RefObject, UIEventHandler } from 'react'

import { uniqueNotices } from '../lib/applicant-notices'
import type { ApplicantNotice, JobPosting, RecommendationItem } from '../lib/contracts'
import { dateLabel, safeSourceUrl, sourceLabel } from '../lib/job-display'
import { AsyncButton } from './async-button'
import { Icon } from './icon'
import { JobReviewStatus } from './job-review-status'
import { MatchRadar, MatchScoreValue } from './match-score'
import { MatchingSourceQuotes } from './matching-source-quotes'
import { ResultWarnings } from './results/result-warnings'

export function JobDetail({
  item,
  saved,
  onToggle,
  onBack,
  notices,
  headingRef,
  scrollRef,
  onScroll,
  reviewActive = false,
}: {
  item: RecommendationItem
  saved: boolean
  onToggle: () => unknown
  onBack: () => void
  notices: ApplicantNotice[]
  headingRef: RefObject<HTMLHeadingElement | null>
  scrollRef?: Ref<HTMLElement>
  onScroll?: UIEventHandler<HTMLElement>
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
      className="card min-h-0 min-w-0 flex-1 border border-base-300 bg-base-100 min-[1100px]:overflow-hidden"
    >
      <div className="shrink-0 p-4 pb-0 sm:px-5">
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
          className="mt-2 text-xl font-semibold tracking-tight wrap-anywhere outline-none sm:text-2xl"
        >
          {job.title}
        </h2>
        <div className="mt-2 flex flex-wrap items-baseline gap-x-4 gap-y-1 text-sm">
          <p className="font-semibold">{job.salary || 'Salary not provided'}</p>
          <p className="text-base-content/65">
            {[job.location, job.employment_type].filter(Boolean).join(' · ')}
          </p>
        </div>
      </div>
      <div className="sticky top-0 z-10 flex shrink-0 flex-wrap gap-2 border-b border-base-300 bg-base-100 p-4 min-[1100px]:static sm:px-5">
        {links[0] && (
          <a
            className="btn btn-primary btn-sm"
            href={links[0]}
            target="_blank"
            rel="noopener noreferrer"
          >
            View job listing <Icon name="external" size={16} />
          </a>
        )}
        <AsyncButton
          className="btn btn-sm"
          aria-label={`${saved ? 'Remove saved job' : 'Save job'}: ${job.title}`}
          aria-pressed={saved}
          onClick={onToggle}
        >
          <Icon name="bookmark" size={17} className={saved ? 'fill-secondary' : ''} />
          {saved ? 'Saved' : 'Save job'}
        </AsyncButton>
      </div>
      <section
        ref={scrollRef}
        onScroll={onScroll}
        aria-label="Job analysis"
        // oxlint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- Keyboard users must be able to scroll this independent pane.
        tabIndex={0}
        className="min-h-0 min-[1100px]:flex-1 min-[1100px]:[scrollbar-gutter:stable] min-[1100px]:overflow-y-auto min-[1100px]:overscroll-y-contain"
      >
        <div className="space-y-5 p-5 text-sm leading-6 sm:space-y-6">
          <JobMatch item={item} />
          <ResultWarnings
            notices={jobNotices}
            listingUrl={links[0]}
            undocumented={(item.analysis_status === 'unavailable' ? [] : item.matching_reasons)
              .filter((reason) => reason.level === 'not_documented')
              .map((reason) => reason.explanation)}
          />
          <Responsibilities job={job} />
          <Preparation item={item} />
          <MatchingSourceQuotes reasons={item.matching_reasons} />
        </div>
        <ListingMetadata job={job} links={links} />
      </section>
    </article>
  )
}

function JobMatch({ item }: { item: RecommendationItem }) {
  if (item.analysis_status === 'unavailable') return null
  const score = item.match_score
  if (!item.recommendation_reason && !score) return null
  return (
    <section className="@container">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h3 className="font-semibold">Why this role</h3>
        {score && <MatchScoreValue score={score} prominent />}
      </div>
      <div
        className={`mt-4 grid gap-5 ${score ? '@min-[34rem]:grid-cols-[minmax(0,1fr)_18rem] @min-[34rem]:items-center' : ''}`}
      >
        <div className="min-w-0">
          {item.recommendation_reason && (
            <p className="text-base-content/75">{item.recommendation_reason}</p>
          )}
          {score?.provisional && score.total !== null && (
            <p className="mt-3 text-xs leading-5 text-base-content/60">
              Some details are missing, so this score may change with more information.
            </p>
          )}
        </div>
        {score && <MatchRadar key={item.job.job_id} score={score} />}
      </div>
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
  const suggestions = [...new Set(item.preparation_suggestions.filter((value) => value.trim()))]
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
    <div className="border-t border-base-300 p-5 text-xs leading-6 text-base-content/60 sm:p-6">
      <p>
        {sourceLabel(job.source)} · Retrieved {dateLabel(job.fetched_at)}
      </p>
      {job.posted_at && <p className="mt-1">Posted {dateLabel(job.posted_at)}</p>}
      {job.expiry_at && <p className="mt-1">Deadline {dateLabel(job.expiry_at)}</p>}
      {job.freshness_status === 'expired' && (
        <p className="mt-2">Applications for this job have closed.</p>
      )}
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
