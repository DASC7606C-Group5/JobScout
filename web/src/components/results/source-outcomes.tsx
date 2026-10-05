import type { SourceOutcome } from '../../lib/contracts'
import { sourceOutcomeRows } from '../../lib/source-outcomes'

const labels: Record<string, string> = {
  ok: '检索成功',
  success: '检索成功',
  empty: '检索成功，无结果',
  blocked: '访问受限',
  unavailable: '暂不可用',
  failed: '检索失败',
  error: '检索失败',
  timeout: '检索超时',
}

export function SourceOutcomes({ outcomes }: { outcomes: SourceOutcome[] }) {
  if (!outcomes.length) return null
  return (
    <details className="mb-5 rounded-xl border border-base-300 bg-base-100 p-4">
      <summary className="cursor-pointer text-sm">检索来源与覆盖情况</summary>
      <ul className="mt-3 space-y-2 text-xs leading-6 text-base-content/70">
        {sourceOutcomeRows(outcomes).map(({ key, outcome, count }) => (
          <li key={key}>
            {outcome.source} · {outcome.target_direction}：
            {outcome.status === 'ok' && outcome.returned_count === 0
              ? '检索成功，无结果'
              : (labels[outcome.status] ?? outcome.status)}{' '}
            · {outcome.returned_count} 个结果
            {outcome.excerpt_count > 0 && ` · ${outcome.excerpt_count} 份仅有摘要`}
            {count > 1 && ` · ${count} 次检索返回相同统计`}
          </li>
        ))}
      </ul>
    </details>
  )
}
