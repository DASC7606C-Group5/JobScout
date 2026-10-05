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
  const { session } = useScoutSession()
  const stage = session?.outcome ?? 'initial'
  const completed = stage === 'completed'
  const count = session?.recommendation?.jobs.length ?? 0
  const pending = session?.recommendation?.pending_jobs.length ?? 0
  return (
    <PageHeading
      eyebrow={completed ? 'YOUR OPPORTUNITIES' : 'YOUR NEXT CHAPTER'}
      title={
        completed
          ? count > 0
            ? `${count} ${count === 1 ? 'match' : 'matches'} to explore`
            : pending > 0
              ? 'More jobs to review'
              : 'Your search results'
          : headings[stage]
      }
      description={
        completed || session?.run_id
          ? ''
          : 'Tell us about your experience and goals to find a role that fits you better.'
      }
    />
  )
}

export function DiscoveryPage() {
  const { session, busy, edit } = useScoutSession()
  const stage = session?.outcome ?? 'initial'
  const completed = stage === 'completed'
  const focused = completed || Boolean(session?.run_id)
  return (
    <>
      <DiscoveryHeading />
      {session?.profile && session.current_stage !== 'confirm' && (
        <section
          className="card mb-5 flex-row flex-wrap items-center justify-between gap-3 border border-base-300 bg-base-100 p-4"
          aria-label="Search criteria"
        >
          <div>
            <h2 className="text-sm font-semibold">Search criteria</h2>
            <p className="mt-1 text-sm text-base-content/65">{criteriaLabel(session.profile)}</p>
          </div>
          <button className="btn btn-ghost btn-sm" disabled={busy} onClick={edit}>
            <Icon name="compass" size={15} />
            Edit search criteria
          </button>
        </section>
      )}
      {!focused && (
        <WorkflowSteps step={session?.search_summary?.confirmed ? 2 : stageSteps[stage]} />
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
    `Up to ${profile.search_options.result_count} matching jobs`,
  ]
    .filter(Boolean)
    .join(' · ')
}
