import { readFileSync } from 'node:fs'

import type { CreateSessionRequest } from '../src/lib/contracts'

type ReplayInput = Pick<
  CreateSessionRequest,
  'description' | 'resume' | 'target_directions' | 'preferences'
>

const dataset = JSON.parse(
  readFileSync(new URL('../../data/replay/scenarios.json', import.meta.url), 'utf8'),
) as { profiles: { case_id: string; input: ReplayInput }[] }

export function replayInput(caseId: string): ReplayInput {
  const scenario = dataset.profiles.find((profile) => profile.case_id === caseId)
  if (!scenario) throw new Error(`Unknown replay case: ${caseId}`)
  return structuredClone(scenario.input)
}
