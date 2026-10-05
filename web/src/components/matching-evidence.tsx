import type { EvidenceReference, MatchingReason } from '../lib/contracts'
import { safeSourceUrl } from '../lib/job-display'

const levels = {
  strong: 'Strong match',
  partial: 'Partial match',
  related_experience: 'Related experience',
  not_evidenced: 'Not found in the materials provided',
}

function evidenceSourceLabel(documentId: string, kind: 'job' | 'profile') {
  if (kind === 'job') return 'Job listing'
  if (documentId === 'resume' || documentId.endsWith(':resume')) return 'Uploaded resume'
  if (documentId === 'description' || documentId.endsWith(':description')) return 'Introduction'
  if (documentId === 'answer' || documentId.includes(':answer:')) return 'Additional answer'
  return 'Additional information'
}

function EvidenceList({
  title,
  evidence,
  kind,
}: {
  title: string
  evidence: EvidenceReference[]
  kind: 'job' | 'profile'
}) {
  return (
    <div>
      <h6 className="text-xs font-semibold text-base-content/70">{title}</h6>
      {evidence.length ? (
        evidence.map((reference) => {
          const url = reference.source_url ? safeSourceUrl(reference.source_url) : null
          return (
            <blockquote
              key={JSON.stringify(reference)}
              className="mt-2 border-l-2 border-base-300 pl-3 text-xs leading-6 text-base-content/70"
            >
              <p className="break-words whitespace-pre-wrap">“{reference.excerpt}”</p>
              <cite className="text-base-content/55 not-italic">
                {evidenceSourceLabel(reference.document_id, kind)}
              </cite>
              {url && (
                <a className="ml-2 link" href={url} target="_blank" rel="noopener noreferrer">
                  Check source
                </a>
              )}
            </blockquote>
          )
        })
      ) : (
        <p className="mt-1 text-xs text-base-content/60">
          No evidence excerpts available to review.
        </p>
      )}
    </div>
  )
}

export function MatchingEvidence({ reasons }: { reasons: MatchingReason[] }) {
  if (!reasons.length)
    return (
      <p className="text-xs text-base-content/60">
        No match evidence provided yet. Check the original job listing.
      </p>
    )
  return (
    <section aria-label="Match reasons and evidence" className="space-y-3">
      <h4 className="text-sm font-semibold">Match reasons and evidence</h4>
      {reasons.map((reason) => (
        <div
          key={JSON.stringify(reason)}
          className="card rounded-xl border border-base-300 bg-base-200/35 card-sm"
        >
          <div className="card-body gap-3 p-4">
            <div className="space-y-2 sm:flex sm:items-start sm:justify-between sm:gap-3 sm:space-y-0">
              <h5 className="card-title min-w-0 text-sm leading-6 break-words">
                {reason.requirement}
              </h5>
              <span className="badge h-auto shrink-0 py-1 text-xs badge-sm">
                {levels[reason.level]}
              </span>
            </div>
            <p className="text-xs leading-6 text-base-content/70">{reason.explanation}</p>
            {reason.level === 'not_evidenced' && (
              <p className="text-xs leading-6 text-base-content/60">
                This means the evidence wasn’t found in the materials you shared; it doesn’t mean
                you lack this skill.
              </p>
            )}
            <div className="space-y-3 border-t border-base-300 pt-3">
              <EvidenceList
                title="Job requirement evidence"
                evidence={reason.job_evidence}
                kind="job"
              />
              <EvidenceList
                title="Your experience evidence"
                evidence={reason.profile_evidence}
                kind="profile"
              />
            </div>
          </div>
        </div>
      ))}
    </section>
  )
}
