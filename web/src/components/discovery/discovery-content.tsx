import { ApplicantRequestError, applicantErrorMessage } from '../../lib/applicant-errors'
import { SessionHttpError } from '../../lib/session-client'
import { useScout } from '../../state/scout-context'
import { useScoutSession } from '../../state/session-context'
import { ClarificationForm } from '../clarification-form'
import { ConversationHistory } from '../conversation-history'
import { Icon } from '../icon'
import { ProfileForm } from '../profile-form'
import { ProfileSummary } from '../profile/profile-summary'
import { Results } from '../results'
import { SearchSummary } from '../search-summary'
import { SearchExperience } from './search-experience'
import { SearchRecord } from './search-record'
import { SearchFailure, SearchLoading } from './search-status'

export function DiscoveryContent() {
  const { error, retry, recovery } = useScoutSession()
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
      <SessionContent />
    </>
  )
}

function SessionContent() {
  const { session, retry, edit, stop, stopping } = useScoutSession()
  const saved = useScout((state) => state.saved)
  const toggleSaved = useScout((state) => state.toggleSaved)
  if (!session) return <ProfileForm />
  const sessionKey = `${session.session_id}:${session.run_id ?? 'profile'}`
  const hasResults = Boolean(
    session.recommendation?.jobs.length || session.recommendation?.pending_jobs.length,
  )
  const results = (
    <Results
      key={sessionKey}
      result={session.recommendation}
      notices={session.notices}
      saved={saved}
      onToggle={toggleSaved}
      onEdit={edit}
      footerActions={<SearchRecord session={session} compact />}
    />
  )
  const searchExperience = (
    <SearchExperience
      key={sessionKey}
      session={session}
      onStop={stop}
      stopping={stopping}
      saved={saved}
      onToggle={toggleSaved}
      onEdit={edit}
    />
  )
  switch (session.outcome) {
    case 'running':
      return <>{session.run_id ? searchExperience : <SearchLoading session={session} />}</>
    case 'paused':
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
      return (
        <>
          <SearchFailure
            errors={session.errors}
            onRetry={retry}
            onEdit={edit}
            retryable={session.retryable}
            compact={hasResults}
          />
          {hasResults && results}
          {!hasResults && <SearchRecord session={session} compact={false} />}
        </>
      )
    case 'completed':
      return searchExperience
  }
}
