import { useScout } from '../../state/scout-context'
import { ClarificationForm } from '../clarification-form'
import { Icon } from '../icon'
import { ProfileForm } from '../profile-form'
import { Results } from '../results'
import { SearchFailure, SearchLoading } from './search-status'

export function DiscoveryContent() {
  const busy = useScout((state) => state.busy)
  const error = useScout((state) => state.error)
  const retry = useScout((state) => state.retry)
  if (busy) return <SearchLoading />
  return (
    <>
      {error && (
        <div role="alert" className="mb-5 alert rounded-xl alert-soft text-sm alert-error">
          <Icon name="info" />
          <span>{error}</span>
          <button
            className="btn btn-sm"
            onClick={() => {
              void retry()
            }}
          >
            重试
          </button>
        </div>
      )}
      <SessionContent />
    </>
  )
}

function SessionContent() {
  const session = useScout((state) => state.session)
  const saved = useScout((state) => state.saved)
  const toggleSaved = useScout((state) => state.toggleSaved)
  const retry = useScout((state) => state.retry)
  const edit = useScout((state) => state.edit)
  if (!session) return <ProfileForm />
  switch (session.current_stage) {
    case 'clarify':
      return (
        <ClarificationForm
          key={`${session.session_id}-${session.clarification_questions.filter((question) => question.status === 'answered').length}`}
          questions={session.clarification_questions}
        />
      )
    case 'failed':
      return (
        <SearchFailure
          errors={session.errors}
          onRetry={() => {
            void retry()
          }}
        />
      )
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
