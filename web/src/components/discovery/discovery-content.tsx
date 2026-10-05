import { ApplicantRequestError, applicantErrorMessage } from '../../lib/applicant-errors'
import { SessionHttpError } from '../../lib/session-client'
import { useScout } from '../../state/scout-context'
import { useScoutSession } from '../../state/session-context'
import { ClarificationForm } from '../clarification-form'
import { ConversationHistory } from '../conversation-history'
import { Icon } from '../icon'
import { ProfileForm } from '../profile-form'
import { Results } from '../results'
import { ResultWarnings } from '../results/result-warnings'
import { SourceOutcomes } from '../results/source-outcomes'
import { SearchSummary } from '../search-summary'
import { SearchFailure, SearchLoading } from './search-status'

export function DiscoveryContent() {
  const { session, busy, error, retry, recovery } = useScoutSession()
  const errorCode =
    error instanceof ApplicantRequestError || error instanceof SessionHttpError
      ? error.code
      : 'request_failed'
  return (
    <>
      {error && (
        <div role="alert" className="mb-5 alert rounded-xl alert-soft text-sm alert-error">
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
  const { session, retry, edit } = useScoutSession()
  const saved = useScout((state) => state.saved)
  const toggleSaved = useScout((state) => state.toggleSaved)
  if (!session) return <ProfileForm />
  switch (session.outcome) {
    case 'running':
      return <SearchLoading stage={session.current_stage} />
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
          {session.notices.length > 0 && (
            <div className="mt-5">
              <ResultWarnings
                notices={session.notices.filter((notice) => notice.scope !== 'job')}
                onEdit={edit}
                collapsed
              />
            </div>
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
            <ResultWarnings
              notices={session.notices.filter((notice) => notice.scope !== 'job')}
              onEdit={edit}
              collapsed
            />
            <SourceOutcomes outcomes={session.source_outcomes} />
            <ConversationHistory session={session} collapsed />
          </div>
        </>
      )
    case 'completed':
      return (
        <>
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
