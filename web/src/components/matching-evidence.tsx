import type { EvidenceReference, MatchingReason } from '../lib/contracts'
import { safeSourceUrl } from '../lib/job-display'

const levels = {
  strong: '充分匹配',
  partial: '部分匹配',
  related_experience: '相关经历',
  not_evidenced: '所提供材料中未体现',
}

function evidenceSourceLabel(documentId: string, kind: 'job' | 'profile') {
  if (kind === 'job') return '岗位来源'
  if (documentId === 'resume' || documentId.endsWith(':resume')) return '已上传简历'
  if (documentId === 'description' || documentId.endsWith(':description')) return '自我介绍'
  if (documentId === 'answer' || documentId.includes(':answer:')) return '补充回答'
  return '个人补充材料'
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
    <section aria-label="匹配理由与证据" className="space-y-3">
      <h4 className="text-sm font-semibold">匹配理由与证据</h4>
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
                这仅表示所提供材料中未找到证据，并不代表你不具备该能力。
              </p>
            )}
            <div className="space-y-3 border-t border-base-300 pt-3">
              <EvidenceList title="岗位要求依据" evidence={reason.job_evidence} kind="job" />
              <EvidenceList
                title="个人经历依据"
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
