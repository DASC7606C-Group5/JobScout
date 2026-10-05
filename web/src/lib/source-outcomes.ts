import type { SourceOutcome } from './contracts'

export function sourceOutcomeRows(outcomes: SourceOutcome[]) {
  const rows = new Map<string, { key: string; outcome: SourceOutcome; count: number }>()
  for (const outcome of outcomes) {
    const key = JSON.stringify(outcome)
    const existing = rows.get(key)
    if (existing) existing.count += 1
    else rows.set(key, { key, outcome, count: 1 })
  }
  return [...rows.values()]
}
