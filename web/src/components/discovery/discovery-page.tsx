import { useScoutSession } from '../../state/session-context'
import { Icon } from '../icon'
import { JourneyAside } from '../journey-aside'
import { PageHeading } from '../layout/page-heading'
import { DiscoveryContent } from './discovery-content'
import { WorkflowSteps } from './workflow-steps'

const headings = {
  initial: '好机会，从认识你开始。',
  paused: '好机会，值得再聊一聊。',
  running: '正在理解你的下一步。',
  completed: '下一站，从这些机会开始。',
  failed: '好机会，从认识你开始。',
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
            ? '在不同方向中发现可能，也为每一次申请多做一点准备。'
            : '聊聊你的经历和期待，让下一份工作更贴近你。'
        }
      >
        {stage !== 'initial' && !busy && (
          <button
            className="btn rounded-lg border border-base-300 bg-base-100 font-normal shadow-none btn-sm"
            onClick={edit}
          >
            <Icon name="compass" size={15} />
            调整求职条件
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
