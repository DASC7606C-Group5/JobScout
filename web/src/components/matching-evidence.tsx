import type { EvidenceReference, MatchingReason } from '../lib/contracts'
import { safeSourceUrl } from '../lib/job-display'

function evidenceSourceLabel(documentId: string, kind: 'job' | 'profile') {
  if (kind === 'job') return 'Job listing'
  if (documentId === 'resume' || documentId.endsWith(':resume')) return 'Uploaded resume'
  if (documentId === 'description' || documentId.endsWith(':description')) return 'Introduction'
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
  if (!evidence.length) return null
  return (
    <div>
      <h5 className="text-xs font-semibold text-base-content/70">{title}</h5>
      {evidence.map((reference) => {
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
      })}
    </div>
  )
}

export function MatchingEvidence({ reasons }: { reasons: MatchingReason[] }) {
  const supported = reasons.filter(
    (reason) => reason.job_evidence.length || reason.profile_evidence.length,
  )
  if (!supported.length) return null
  return (
    <details className="collapse-arrow collapse rounded-xl border border-base-300 bg-base-100">
      <summary className="collapse-title text-sm font-medium">View supporting evidence</summary>
      <div className="collapse-content space-y-5">
        {supported.map((reason) => (
          <section key={JSON.stringify(reason)} className="space-y-3">
            <h4 className="text-sm font-semibold break-words">{reason.requirement}</h4>
            <EvidenceList title="Job requirement" evidence={reason.job_evidence} kind="job" />
            <EvidenceList
              title="Your experience"
              evidence={reason.profile_evidence}
              kind="profile"
            />
          </section>
        ))}
      </div>
    </details>
  )
}
