import type {
  HiddenJobReason,
  RecommendationItem,
  ResultExclusion,
  ResultReaction,
} from '../../lib/contracts'

export function HiddenResults({
  jobs,
  reasons,
  exclusions,
  feedbackByJob,
  disabled,
  onFeedback,
}: {
  jobs: RecommendationItem[]
  reasons: HiddenJobReason[]
  exclusions: ResultExclusion[]
  feedbackByJob: Record<string, ResultReaction>
  disabled: boolean
  onFeedback?: (jobId: string, reaction: ResultReaction | null) => unknown
}) {
  if (!jobs.length && !exclusions.length) return null
  const rules = new Map(exclusions.map((rule) => [rule.exclusion_id, rule.description]))
  return (
    <details className="collapse-arrow collapse mb-3 shrink-0 border border-base-300 bg-base-100">
      <summary className="collapse-title text-sm font-medium">
        Hidden jobs ({jobs.length}) · Exclusion rules ({exclusions.length})
      </summary>
      <div className="collapse-content text-sm">
        {exclusions.length > 0 && (
          <section aria-label="Exclusion rules" className="mb-4 space-y-2">
            <h3 className="font-semibold">Exclusion rules</h3>
            <ul className="list-disc space-y-1 pl-5">
              {exclusions.map((rule) => (
                <li key={rule.exclusion_id}>{rule.description}</li>
              ))}
            </ul>
            <p className="text-base-content/65">
              To cancel a rule, name it in Continue with these results. Jobs hidden with Not for me
              stay hidden.
            </p>
          </section>
        )}
        <ul aria-label="Hidden jobs" className="max-h-72 space-y-3 overflow-y-auto">
          {jobs.map(({ job }) => {
            const matched = reasons.filter(
              (reason) => reason.job_id === job.job_id && reason.kind === 'excluded',
            )
            const disliked = feedbackByJob[job.job_id] === 'not_interested'
            return (
              <li
                key={job.job_id}
                className="flex flex-wrap items-center justify-between gap-3 border-t border-base-300 pt-3"
              >
                <div className="min-w-0 flex-1">
                  <h3 className="font-medium wrap-anywhere">{job.title}</h3>
                  <p className="text-base-content/65">{job.company}</p>
                  {disliked && <p className="mt-1 text-xs">Hidden by Not for me</p>}
                  {matched.map((reason) => (
                    <p key={reason.exclusion_id} className="mt-1 text-xs">
                      Excluded: {rules.get(reason.exclusion_id ?? '') ?? 'Exclusion rule'}
                    </p>
                  ))}
                </div>
                {disliked && onFeedback && (
                  <button
                    type="button"
                    className="btn btn-sm"
                    disabled={disabled}
                    onClick={() => onFeedback(job.job_id, null)}
                    aria-label={`Undo Not for me: ${job.title}`}
                  >
                    Undo Not for me
                  </button>
                )}
                {matched.length > 0 && (
                  <p className="w-full text-xs text-base-content/65">
                    Cancel the matching exclusion rule to show this job.
                  </p>
                )}
              </li>
            )
          })}
        </ul>
      </div>
    </details>
  )
}
