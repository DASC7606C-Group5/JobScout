import { useScoutSession } from '../../state/session-context'
import { Icon } from '../icon'
import { JourneyAside } from '../journey-aside'
import { PageHeading } from '../layout/page-heading'
import { DiscoveryContent } from './discovery-content'
import { WorkflowSteps } from './workflow-steps'

const headings = {
  initial: 'Finding the right opportunity starts with getting to know you.',
  paused: 'Let’s talk a little more about the right opportunity for you.',
  running: 'We’re figuring out your next step.',
  completed: 'Your next step could start with one of these opportunities.',
  failed: 'Finding the right opportunity starts with getting to know you.',
}
const stageSteps = { initial: 0, paused: 1, running: 1, failed: 2, completed: 3 }

export function DiscoveryPage() {
  const { session, busy, edit } = useScoutSession()
  const stage = session?.outcome ?? 'initial'
  const completed = stage === 'completed'
  return (
    <>
      <PageHeading
        eyebrow={completed ? 'YOUR NEXT OPPORTUNITIES' : 'YOUR NEXT CHAPTER'}
        title={headings[stage]}
        description={
          completed
            ? 'Explore possibilities in different directions and feel more prepared for each application.'
            : 'Tell us about your experience and goals to find a role that fits you better.'
        }
      >
        {stage !== 'initial' && !busy && (
          <button
            className="btn rounded-lg border border-base-300 bg-base-100 font-normal shadow-none btn-sm"
            onClick={edit}
          >
            <Icon name="compass" size={15} />
            Edit search criteria
          </button>
        )}
      </PageHeading>
      <WorkflowSteps step={session?.search_summary?.confirmed ? 2 : stageSteps[stage]} />
      <div
        aria-busy={busy}
        className={`grid items-start gap-6 ${completed ? '' : 'min-[1100px]:grid-cols-[minmax(0,1fr)_280px]'}`}
      >
        <div className="min-w-0">
          <DiscoveryContent />
        </div>
        {!completed && <JourneyAside />}
      </div>
    </>
  )
}
