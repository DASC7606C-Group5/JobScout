import type { ClarificationMessage } from '../lib/contracts'
import { collectAnswers, pendingQuestions } from '../lib/conversation'
import { useScoutSession } from '../state/session-context'
import { useSessionDraft, type SessionDraftValues } from '../state/use-session-draft'
import { DraftStatus } from './draft-status'
import { Icon } from './icon'
import { QuestionControl } from './question-control'

const emptyDraft: SessionDraftValues['clarification'] = { values: {}, skipped: [], message: '' }

export function ClarificationForm({
  questions,
  compact = false,
}: {
  questions: ClarificationMessage[]
  compact?: boolean
}) {
  const { answer, busy, pending: submitting } = useScoutSession()
  const pending = pendingQuestions(questions)
  const draft = useSessionDraft('clarification', emptyDraft)
  const {
    value: { values, skipped, message },
    setValue: setDraft,
  } = draft
  const [error, setError] = useState('')
  const skippedIds = new Set(skipped)
  return (
    <form
      noValidate
      className="card border border-base-300 bg-base-100"
      onCompositionStart={draft.onCompositionStart}
      onCompositionEnd={draft.onCompositionEnd}
      onSubmit={(event) => {
        event.preventDefault()
        const answers = collectAnswers(pending, values, skipped)
        if (!answers.length && !message.trim() && !skipped.length) {
          setError('Answer the questions, skip optional ones, or add a note.')
          return
        }
        setError('')
        void answer({ answers, message: message.trim(), skipped_question_ids: skipped })
      }}
    >
      <fieldset
        disabled={busy || draft.status === 'loading'}
        className={`min-w-0 space-y-5 ${compact ? 'p-4' : 'p-5 sm:space-y-6 sm:p-6'}`}
      >
        {pending.map((question) => (
          <QuestionControl
            key={question.question_id}
            question={question}
            value={values[question.question_id] ?? ''}
            skipped={skippedIds.has(question.question_id)}
            onChange={(value) =>
              setDraft((previous) => ({
                ...previous,
                values: { ...previous.values, [question.question_id]: value },
              }))
            }
            onSkip={(checked) =>
              setDraft((previous) => ({
                ...previous,
                skipped: checked
                  ? [...previous.skipped, question.question_id]
                  : previous.skipped.filter((id) => id !== question.question_id),
              }))
            }
          />
        ))}
        <div>
          <label htmlFor="conversation-message" className="mb-2 block text-sm font-medium">
            Add a note or correction
          </label>
          <textarea
            id="conversation-message"
            className="textarea field-sizing-content max-h-96 min-h-24 w-full resize-none border border-base-300 bg-base-200/25 text-base leading-6 sm:text-sm"
            value={message}
            onChange={(event) =>
              setDraft((previous) => ({ ...previous, message: event.target.value }))
            }
            maxLength={10000}
            placeholder="For example: I’m interested in data analysis and open to roles in Hong Kong or Shenzhen."
          />
        </div>
        {error && (
          <p role="alert" className="alert alert-soft text-sm alert-error">
            {error}
          </p>
        )}
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-base-300 pt-4">
          <DraftStatus {...draft} />
          <button
            className="btn min-w-40 border-0 btn-primary"
            type="submit"
            aria-busy={submitting}
          >
            {submitting && (
              <span className="loading loading-xs loading-spinner" aria-hidden="true" />
            )}
            Send and continue
            <Icon name="arrow" size={18} />
          </button>
        </div>
      </fieldset>
    </form>
  )
}
import { useState } from 'react'
