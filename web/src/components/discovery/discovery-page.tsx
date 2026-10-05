import { useNavigate } from '@tanstack/react-router'

import type { UserProfile } from '../../lib/contracts'
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
  failed: 'Let’s get your search back on track.',
}
const stageSteps = { initial: 0, paused: 1, running: 1, failed: 2 }

function DiscoveryHeading() {
  const { session, busy, edit } = useScoutSession()
  const navigate = useNavigate()
  const stage = session?.outcome ?? 'initial'
  const completed = stage === 'completed'
  const count = session?.recommendation?.jobs.length ?? 0
  const profile = session?.profile
  const criteria = criteriaLabel(profile)
  function editSearch() {
    void navigate({ to: '/', search: {}, replace: true })
    edit()
  }
  return (
    <PageHeading
      eyebrow={completed ? 'YOUR OPPORTUNITIES' : 'YOUR NEXT CHAPTER'}
      title={completed ? `${count} ${count === 1 ? 'job' : 'jobs'} to explore` : headings[stage]}
      description={
        completed
          ? criteria
          : 'Tell us about your experience and goals to find a role that fits you better.'
      }
    >
      {stage !== 'initial' && !busy && (
        <button
          className="btn rounded-lg border border-base-300 bg-base-100 font-normal shadow-none btn-sm"
          onClick={editSearch}
        >
          <Icon name="compass" size={15} />
          Edit search criteria
        </button>
      )}
    </PageHeading>
  )
}

export function DiscoveryPage() {
  const { session, busy } = useScoutSession()
  const stage = session?.outcome ?? 'initial'
  const completed = stage === 'completed'
  return (
    <>
      <DiscoveryHeading />
      {!completed && (
        <WorkflowSteps step={session?.search_summary?.confirmed ? 2 : stageSteps[stage]} />
      )}
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

function criteriaLabel(profile: UserProfile | null | undefined) {
  if (!profile) return ''
  return [
    ...profile.target_directions,
    profile.preferences.location_unrestricted ? 'Any location' : profile.preferences.location,
    profile.preferences.employment_type_unrestricted
      ? 'Any employment type'
      : profile.preferences.employment_type,
  ]
    .filter(Boolean)
    .join(' · ')
}
