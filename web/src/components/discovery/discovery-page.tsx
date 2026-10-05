import type { ScoutSession } from '../../lib/contracts'
import { searchPhase } from '../../lib/search-phase'
import { useScoutSession } from '../../state/session-context'
import { JourneyAside } from '../journey-aside'
import { PageHeading } from '../layout/page-heading'
import { StepTransition } from '../layout/step-transition'
import { DiscoveryContent } from './discovery-content'
import { SearchCriteria } from './search-criteria'
import { WorkflowSteps } from './workflow-steps'

const headings = {
  initial: 'Finding the right opportunity starts with getting to know you.',
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
  if (session.outcome === 'completed') {
    const count = session.recommendation?.jobs.length ?? 0
    return count > 0
      ? `${count} ${count === 1 ? 'match' : 'matches'} to explore`
      : 'Your search results'
  }
  if (session.outcome === 'running' && searchPhase(session) === 'profile')
    return 'Reviewing your profile.'
  if (session.outcome === 'paused' && session.current_stage === 'confirm')
    return 'Confirm your search criteria.'
  return headings[session.outcome]
}

function DiscoveryHeading() {
  const { session } = useScoutSession()
  const stage = session?.outcome ?? 'initial'
  const completed = stage === 'completed'
  return (
    <PageHeading
      eyebrow={completed ? 'YOUR OPPORTUNITIES' : 'YOUR NEXT CHAPTER'}
      title={discoveryTitle(session)}
      description={
        stage === 'initial'
          ? 'Tell us about your experience and goals to find a role that fits you better.'
          : ''
      }
    />
  )
}

export function DiscoveryPage() {
  const { session, busy, canEdit, edit } = useScoutSession()
  const stage = session?.outcome ?? 'initial'
  const completed = stage === 'completed'
  const focused = completed || stage === 'running' || Boolean(session?.run_id)
  return (
    <div className="[--job-detail-top:6rem]">
      <DiscoveryHeading />
      <WorkflowSteps step={workflowStep(session)} />
      <StepTransition step={transitionStep(session)}>
        {session?.profile && session.current_stage !== 'confirm' && (
          <SearchCriteria
            key={session.session_id}
            profile={session.profile}
            canEdit={canEdit}
            onEdit={edit}
          />
        )}
        <div
          aria-busy={busy}
          className={`grid items-start gap-6 ${focused ? '' : 'min-[1100px]:grid-cols-[minmax(0,1fr)_280px]'}`}
        >
          <div className="min-w-0">
            <DiscoveryContent />
          </div>
          {!focused && <JourneyAside />}
        </div>
      </StepTransition>
    </div>
  )
}
