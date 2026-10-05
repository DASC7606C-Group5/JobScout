import { ApplicantRequestError, applicantErrorMessage } from '../../lib/applicant-errors'
import { SessionHttpError } from '../../lib/session-client'
import { useScout } from '../../state/scout-context'
import { useScoutSession } from '../../state/session-context'
import { ClarificationForm } from '../clarification-form'
import { ConversationHistory } from '../conversation-history'
import { Icon } from '../icon'
import { ProfileForm } from '../profile-form'
import { Results } from '../results'
import { SourceOutcomes } from '../results/source-outcomes'
import { SearchSummary } from '../search-summary'
import { SearchActivity, SearchFailure, SearchLoading } from './search-status'

export function DiscoveryContent() {
  const { session, busy, error, retry, recovery } = useScoutSession()
  const errorCode =
    error instanceof ApplicantRequestError || error instanceof SessionHttpError
      ? error.code
      : 'request_failed'
  return (
    <>
      {error && (
        <div role="alert" className="mb-5 alert alert-soft text-sm alert-error">
          <Icon name="info" />
          <span>{applicantErrorMessage(errorCode)}</span>
          <button className="btn btn-sm" onClick={retry}>
            {recovery === 'edit'
              ? 'Start over'
              : recovery === 'refresh'
                ? 'Reload search'
                : recovery === 'correct'
                  ? 'Edit submission'
                  : 'Retry'}
          </button>
        </div>
      )}
      {session?.mode === 'replay' && (
        <output className="mb-4 alert border-base-300 bg-base-200/50 text-sm text-base-content">
          <Icon name="info" size={18} />
          <span>Replay demo</span>
        </output>
      )}
      {busy && session?.outcome !== 'running' && (
        <output className="mb-4 block text-sm">Working…</output>
      )}
      <SessionContent />
    </>
  )
}

function SessionContent() {
  const { session, retry, edit, stop, stopping } = useScoutSession()
  const saved = useScout((state) => state.saved)
  const toggleSaved = useScout((state) => state.toggleSaved)
  if (!session) return <ProfileForm />
  switch (session.outcome) {
    case 'running':
      return <SearchLoading session={session} onStop={stop} stopping={stopping} />
    case 'paused':
      return (
        <>
          <ConversationHistory session={session} />
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
              {session.search_summary && (
                <div className="mt-5">
                  <SearchSummary
                    key={`${session.session_id}-${session.revision}`}
                    summary={session.search_summary}
                  />
                </div>
              )}
            </>
          )}
        </>
      )
    case 'failed':
      return (
        <>
          <SearchFailure
            errors={session.errors}
            onRetry={retry}
            onEdit={edit}
            retryable={session.retryable}
          />
          <div className="mt-5 space-y-5">
            <SearchActivity session={session} />
            <SourceOutcomes outcomes={session.source_outcomes} />
            <ConversationHistory session={session} collapsed />
          </div>
        </>
      )
    case 'completed':
      return (
        <>
          {session.run_id && session.stop_reason && session.stop_reason !== 'target_reached' && (
            <div className="mb-6">
              <SearchActivity session={session} />
            </div>
          )}
          <Results
            key={session.session_id}
            result={session.recommendation}
            notices={session.notices}
            saved={saved}
            onToggle={toggleSaved}
            onEdit={edit}
          />
          <div className="mt-6 space-y-5">
            <SourceOutcomes outcomes={session.source_outcomes} />
            <ConversationHistory session={session} collapsed />
          </div>
        </>
      )
  }
}
