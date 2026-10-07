import type { SourceOutcome } from '../../lib/contracts'
import { sourceLabel } from '../../lib/job-display'

const labels: Record<string, string> = {
  ok: 'Complete',
  success: 'Complete',
  partial: 'Partial',
  empty: 'Empty',
  blocked: 'Unavailable',
  unavailable: 'Unavailable',
  failed: 'Failed',
  error: 'Failed',
  timeout: 'Timeout',
}

export function SourceOutcomes({ outcomes }: { outcomes: SourceOutcome[] }) {
  if (!outcomes.length) return null
  const rows = new Map(
    outcomes.map((outcome) => [
      JSON.stringify([outcome.source, outcome.target_direction, outcome.status]),
      outcome,
    ]),
  )
  return (
    <details className="collapse-arrow collapse border border-base-300 bg-base-100">
      <summary className="collapse-title text-sm font-medium">Sources and search coverage</summary>
      <div className="collapse-content px-0">
        <ul className="divide-y divide-base-300 text-xs leading-6 text-base-content/70">
          {[...rows].map(([key, outcome]) => (
            <li key={key} className="px-4 py-3 first:pt-0 last:pb-0">
              <div className="space-y-1 sm:flex sm:items-start sm:justify-between sm:gap-3 sm:space-y-0">
                <p className="font-medium break-words text-base-content">
                  {sourceLabel(outcome.source)} · {outcome.target_direction}
                </p>
                <span className="badge h-auto shrink-0 py-1 text-xs badge-sm">
                  {(outcome.status === 'ok' || outcome.status === 'success') &&
                  outcome.returned_count === 0
                    ? 'Empty'
                    : (labels[outcome.status] ?? 'Unknown')}
                </span>
              </div>
            </li>
          ))}
        </ul>
      </div>
    </details>
  )
}
