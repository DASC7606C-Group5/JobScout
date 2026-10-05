import type { EvidenceReference, MatchingReason } from '../lib/contracts'
import { safeSourceUrl } from '../lib/job-display'

const levels = {
  strong: '充分匹配',
  partial: '部分匹配',
  related_experience: '相关经历',
  not_evidenced: '所提供材料中未体现',
}

function EvidenceList({ title, evidence }: { title: string; evidence: EvidenceReference[] }) {
  return (
    <div>
      <h5 className="mt-3 text-xs font-semibold">{title}</h5>
      {evidence.length ? (
        evidence.map((reference) => {
          const url = reference.source_url ? safeSourceUrl(reference.source_url) : null
          return (
            <blockquote
              key={JSON.stringify(reference)}
              className="mt-2 border-l-2 border-base-300 pl-3 text-xs text-base-content/70"
            >
              <p className="whitespace-pre-wrap">“{reference.excerpt}”</p>
              <cite className="text-base-content/50 not-italic">{reference.document_id}</cite>
              {url && (
                <a className="ml-2 underline" href={url} target="_blank" rel="noopener noreferrer">
                  核对来源
                </a>
              )}
            </blockquote>
          )
        })
      ) : (
        <p className="mt-1 text-xs text-base-content/60">未提供可核对的材料摘录。</p>
      )}
    </div>
  )
}

export function MatchingEvidence({ reasons }: { reasons: MatchingReason[] }) {
  if (!reasons.length)
    return <p className="text-xs text-base-content/60">暂未提供匹配证据，请核对岗位原文。</p>
  return (
    <section aria-label="匹配理由与证据" className="space-y-4">
      <h4 className="font-semibold">匹配理由与证据</h4>
      {reasons.map((reason) => (
        <div key={JSON.stringify(reason)} className="rounded-xl border border-base-300 p-4">
          <h5 className="font-medium">{reason.requirement}</h5>
          <p className="mt-1 text-xs font-medium">{levels[reason.level]}</p>
          <p className="mt-2 text-sm text-base-content/70">{reason.explanation}</p>
          {reason.level === 'not_evidenced' && (
            <p className="mt-2 text-xs text-base-content/60">
              这仅表示所提供材料中未找到证据，并不代表你不具备该能力。
            </p>
          )}
          <EvidenceList title="岗位要求依据" evidence={reason.job_evidence} />
          <EvidenceList title="个人经历依据" evidence={reason.profile_evidence} />
        </div>
      ))}
    </section>
  )
}
