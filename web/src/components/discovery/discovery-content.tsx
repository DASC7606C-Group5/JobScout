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
  return (
    <>
      {error && (
        <div role="alert" className="mb-5 alert rounded-xl alert-soft text-sm alert-error">
          <Icon name="info" />
          <span>{error.message}</span>
          <button className="btn btn-sm" onClick={retry}>
            {recovery === 'edit'
              ? 'Start over'
              : recovery === 'refresh'
                ? 'Refresh session'
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
      <SessionWarnings />
      {busy && session?.outcome !== 'running' && (
        <output className="mb-4 block text-sm">Working…</output>
      )}
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
        </>
      )
    case 'failed':
      return (
        <>
          <ConversationHistory session={session} />
          <SearchFailure errors={session.errors} onRetry={retry} retryable={session.retryable} />
          <SourceOutcomes outcomes={session.source_outcomes} />
        </>
      )
    case 'completed':
      return (
        <>
          <ConversationHistory session={session} collapsed />
          {session.recommendation?.introduction && (
            <p className="card mb-5 border-base-300 bg-base-100 p-5 text-sm leading-7 card-border">
              {session.recommendation.introduction}
            </p>
          )}
          <SourceOutcomes outcomes={session.source_outcomes} />
          <Results
            key={session.session_id}
            result={session.recommendation}
            saved={saved}
            onToggle={toggleSaved}
            onEdit={edit}
          />
        </>
      )
  }
}
