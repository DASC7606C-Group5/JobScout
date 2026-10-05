import type { SourceQuoteReference, MatchingReason } from '../lib/contracts'
import { safeSourceUrl } from '../lib/job-display'

function sourceLabel(documentId: string, kind: 'job' | 'profile') {
  if (kind === 'job') return 'Job listing'
  if (documentId === 'resume' || documentId.endsWith(':resume')) return 'Uploaded resume'
  if (documentId === 'description' || documentId.endsWith(':description')) return 'Introduction'
  return 'Additional information'
}

function SourceQuoteList({
  title,
  quotes,
  kind,
}: {
  title: string
  quotes: SourceQuoteReference[]
  kind: 'job' | 'profile'
}) {
  if (!quotes.length) return null
  return (
    <div>
      <h5 className="text-xs font-semibold text-base-content/70">{title}</h5>
      {quotes.map((reference) => {
        const url = reference.source_url ? safeSourceUrl(reference.source_url) : null
        return (
          <blockquote
            key={JSON.stringify(reference)}
            className="mt-2 border-l-2 border-base-300 pl-3 text-xs leading-6 text-base-content/70"
          >
            <p className="break-words whitespace-pre-wrap">“{reference.excerpt}”</p>
            <cite className="text-base-content/55 not-italic">
              {sourceLabel(reference.document_id, kind)}
            </cite>
            {url && (
              <a className="ml-2 link" href={url} target="_blank" rel="noopener noreferrer">
                Check source
              </a>
            )}
          </blockquote>
        )
      })}
    </div>
  )
}

export function MatchingSourceQuotes({ reasons }: { reasons: MatchingReason[] }) {
  const reasonsWithQuotes = reasons.filter(
    (reason) => reason.job_source_quotes.length || reason.profile_source_quotes.length,
  )
  if (!reasonsWithQuotes.length) return null
  return (
    <details className="collapse-arrow collapse rounded-xl border border-base-300 bg-base-100">
      <summary className="collapse-title text-sm font-medium">View source excerpts</summary>
      <div className="collapse-content space-y-5">
        {reasonsWithQuotes.map((reason) => (
          <section key={JSON.stringify(reason)} className="space-y-3">
            <h4 className="text-sm font-semibold break-words">{reason.requirement}</h4>
            <SourceQuoteList title="Job requirement" quotes={reason.job_source_quotes} kind="job" />
            <SourceQuoteList
              title="Your experience"
              quotes={reason.profile_source_quotes}
              kind="profile"
            />
          </section>
        ))}
      </div>
    </details>
  )
}
