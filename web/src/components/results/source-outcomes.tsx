import type { SourceOutcome } from '../../lib/contracts'
import { sourceOutcomeRows } from '../../lib/source-outcomes'

const labels: Record<string, string> = {
  ok: 'Search complete',
  success: 'Search complete',
  empty: 'Search complete, no results',
  blocked: 'Access restricted',
  unavailable: 'Temporarily unavailable',
  failed: 'Search failed',
  error: 'Search failed',
  timeout: 'Search timed out',
}

export function SourceOutcomes({ outcomes }: { outcomes: SourceOutcome[] }) {
  if (!outcomes.length) return null
  return (
    <details className="collapse-arrow collapse mb-5 rounded-xl border border-base-300 bg-base-100">
      <summary className="collapse-title text-sm font-medium">Sources and search coverage</summary>
      <div className="collapse-content">
        <ul className="divide-y divide-base-300 text-xs leading-6 text-base-content/70">
          {sourceOutcomeRows(outcomes).map(({ key, outcome, count }) => (
            <li key={key} className="py-3 first:pt-0 last:pb-0">
              <div className="space-y-1 sm:flex sm:items-start sm:justify-between sm:gap-3 sm:space-y-0">
                <p className="font-medium break-words text-base-content">
                  {outcome.source} · {outcome.target_direction}:
                </p>
                <span className="badge h-auto shrink-0 py-1 text-xs badge-sm">
                  {(outcome.status === 'ok' || outcome.status === 'success') &&
                  outcome.returned_count === 0
                    ? 'Search complete, no results'
                    : (labels[outcome.status] ?? 'Search status unconfirmed')}
                </span>
              </div>
              <p className="mt-1">
                {outcome.returned_count} {outcome.returned_count === 1 ? 'result' : 'results'}
                {outcome.excerpt_count > 0 &&
                  ` · ${outcome.excerpt_count} ${outcome.excerpt_count === 1 ? 'summary' : 'summaries'} only`}
                {outcome.incomplete_count > 0 &&
                  ` · ${outcome.incomplete_count} incomplete ${outcome.incomplete_count === 1 ? 'listing' : 'listings'}`}
                {count > 1 && ` · Same counts returned across ${count} searches`}
              </p>
            </li>
          ))}
        </ul>
      </div>
    </details>
  )
}
