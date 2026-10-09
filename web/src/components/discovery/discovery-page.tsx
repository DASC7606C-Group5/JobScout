import type { ScoutSession } from '../../lib/contracts'
import { searchPhase } from '../../lib/search-phase'
import { searchPresentation } from '../../lib/search-presentation'
import { useScoutSession } from '../../state/session-context'
import { JourneyAside } from '../journey-aside'
import { PageHeading } from '../layout/page-heading'
import { StepTransition } from '../layout/step-transition'
import { ResultConversation } from '../result-conversation'
import { DiscoveryContent } from './discovery-content'
import { SearchCriteria } from './search-criteria'
import { WorkflowSteps } from './workflow-steps'

const headings = {
  initial: 'Tell us about yourself',
  queued: 'Your request is in the queue.',
  cancelled: 'Your queued request was cancelled.',
  paused: 'Tell us a little more.',
  running: 'Finding your next role.',
  failed: 'Let’s get your search back on track.',
}
function workflowStep(session: ScoutSession | null) {
  if (!session) return 0
  if (session.outcome === 'completed' || searchPhase(session) !== 'profile') return 2
  if (
    session.outcome === 'paused' ||
    session.search_summary ||
    session.clarification_questions.length
  )
    return 1
  return 0
}

function transitionStep(session: ScoutSession | null) {
  if (!session) return 'introduction'
  if (session.outcome === 'running') {
    const phase = searchPhase(session)
    return phase === 'preparing' ? 'search' : phase
  }
  return `${session.outcome}-${session.current_stage}`
}

function discoveryTitle(session: ScoutSession | null) {
  if (!session) return headings.initial
  if (session.current_stage === 'follow_up_clarify') return 'Continuing with your results'
  if (session.outcome === 'completed') {
    const hidden = new Set(session.hidden_job_ids)
    const count = [
      ...(session.recommendation?.jobs ?? []),
      ...(session.recommendation?.pending_jobs ?? []),
    ].filter(({ job }) => !hidden.has(job.job_id)).length
    return `${count} ${count === 1 ? 'job' : 'jobs'}`
  }
  if (session.outcome === 'running') return searchPresentation(session).heading
  if (session.outcome === 'paused' && session.current_stage === 'confirm')
    return 'Review your profile and search criteria'
  return headings[session.outcome]
}

function DiscoveryHeading({ focused }: { focused: boolean }) {
  const { session, canEdit, edit } = useScoutSession()
  return (
    <PageHeading title={discoveryTitle(session)}>
      <div className="ml-auto flex flex-wrap items-center justify-end gap-2">
        {session?.mode === 'replay' && (
          <span className="badge badge-ghost badge-sm">Replay demo</span>
        )}
        {focused && session?.profile && (
          <SearchCriteria
            key={session.session_id}
            profile={session.profile}
            canEdit={canEdit}
            onEdit={edit}
            resultPreferences={session.result_preferences}
          />
        )}
      </div>
    </PageHeading>
  )
}

export function DiscoveryPage() {
  const { session, busy } = useScoutSession()
  const stage = session?.outcome ?? 'initial'
  const completed = stage === 'completed'
  const step = workflowStep(session)
  const focused = completed || step === 2
  return (
    <div className="results-layout">
      <DiscoveryHeading focused={focused} />
      {!focused && <WorkflowSteps step={step} />}
      <StepTransition step={transitionStep(session)} className="results-layout">
        <div
          aria-busy={busy}
          className={`results-layout grid items-start gap-6 ${focused ? '' : 'min-[1100px]:grid-cols-[minmax(0,1fr)_280px]'}`}
        >
          <div className="results-layout min-w-0">
            <DiscoveryContent />
          </div>
          {!focused && <JourneyAside />}
        </div>
      </StepTransition>
      {session?.recommendation && <ResultConversation key={session.session_id} session={session} />}
    </div>
  )
}
