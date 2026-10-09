import { useScout } from '../../state/scout-context'
import { useScoutSession } from '../../state/session-context'
import { AsyncButton } from '../async-button'
import { ClarificationForm } from '../clarification-form'
import { ConversationHistory } from '../conversation-history'
import { ProfileForm } from '../profile-form'
import { ProfileSummary } from '../profile/profile-summary'
import { SearchSummary } from '../search-summary'
import { QueuedOperation } from './queued-operation'
import { SearchExperience } from './search-experience'
import { SearchLoading } from './search-status'

export function DiscoveryContent() {
  return <SessionContent />
}

function SessionContent() {
  const { session, retry, edit, stop, stopping, cancel, cancelling, feedback, busy } =
    useScoutSession()
  const saved = useScout((state) => state.saved)
  const toggleSaved = useScout((state) => state.toggleSaved)
  if (!session) return <ProfileForm />
  const sessionKey = session.session_id
  const searchExperience = (
    <SearchExperience
      key={sessionKey}
      session={session}
      onStop={stop}
      stopping={stopping}
      saved={saved}
      onToggle={toggleSaved}
      onEdit={edit}
      onRetry={retry}
      onFeedback={feedback}
      feedbackDisabled={busy || session.outcome !== 'completed'}
    />
  )
  switch (session.outcome) {
    case 'queued':
      return <QueuedOperation session={session} onCancel={cancel} cancelling={cancelling} />
    case 'cancelled':
      return (
        <div className="card border border-base-300 bg-base-100">
          <div className="card-body">
            <p>Your information is saved.</p>
            <div className="card-actions">
              <AsyncButton type="button" className="btn btn-primary" onClick={retry}>
                Try again
              </AsyncButton>
              <AsyncButton type="button" className="btn btn-ghost" onClick={edit}>
                Edit criteria
              </AsyncButton>
            </div>
          </div>
        </div>
      )
    case 'running':
      return session.run_id || session.operation_kind === 'follow_up' ? (
        searchExperience
      ) : (
        <SearchLoading session={session} />
      )
    case 'paused':
      if (session.current_stage === 'follow_up_clarify') return searchExperience
      return (
        <>
          {session.current_stage === 'confirm' && session.search_summary ? (
            <SearchSummary
              key={`${session.session_id}-${session.revision}`}
              summary={session.search_summary}
            />
          ) : (
            <>
              <ClarificationForm
                key={`${session.session_id}-${session.revision}`}
                questions={session.clarification_questions}
              />
              {session.profile && (
                <div className="mt-5">
                  <ProfileSummary profile={session.profile} />
                </div>
              )}
            </>
          )}
          <div className="mt-5">
            <ConversationHistory session={session} collapsed />
          </div>
        </>
      )
    case 'failed':
    case 'completed':
      return searchExperience
  }
}
