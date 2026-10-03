import { useScout } from '../../state/scout-context'
import { useScoutSession } from '../../state/session-context'
import { ClarificationForm } from '../clarification-form'
import { Icon } from '../icon'
import { ProfileForm } from '../profile-form'
import { Results } from '../results'
import { ResultWarnings } from '../results/result-warnings'
import { SearchFailure, SearchLoading } from './search-status'

export function DiscoveryContent() {
  const { busy, error, retry, recovery } = useScoutSession()
  if (busy) return <SearchLoading />
  return (
    <>
      {error && (
        <div role="alert" className="mb-5 alert rounded-xl alert-soft text-sm alert-error">
          <Icon name="info" />
          <span>{error.message}</span>
          <button className="btn btn-sm" onClick={retry}>
            {recovery === 'edit' ? '调整求职条件' : recovery === 'refresh' ? '刷新会话' : '重试'}
          </button>
        </div>
      )}
      <SessionWarnings />
      <SessionContent />
    </>
  )
}

function SessionWarnings() {
  const { session } = useScoutSession()
  const recommendationWarnings = new Set(session?.recommendation?.warnings ?? [])
  const warnings = [...new Set(session?.warnings ?? [])].filter(
    (warning) => !recommendationWarnings.has(warning),
  )
  return <ResultWarnings warnings={warnings} />
}

function SessionContent() {
  const { session, retry, edit } = useScoutSession()
  const saved = useScout((state) => state.saved)
  const toggleSaved = useScout((state) => state.toggleSaved)
  if (!session) return <ProfileForm />
  switch (session.outcome) {
    case 'paused':
      return (
        <ClarificationForm
          key={JSON.stringify([session.session_id, session.clarification_questions])}
          questions={session.clarification_questions}
        />
      )
    case 'failed':
      return <SearchFailure errors={session.errors} onRetry={retry} />
    case 'completed':
      return (
        <Results
          key={session.session_id}
          result={session.recommendation}
          saved={saved}
          onToggle={toggleSaved}
          onEdit={edit}
        />
      )
  }
}
