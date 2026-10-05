import { useState } from 'react'

import type { ClarificationMessage } from '../lib/contracts'
import { answerValidation, collectAnswers, pendingQuestions } from '../lib/conversation'
import { useScoutSession } from '../state/session-context'
import { useSessionDraft, type SessionDraftValues } from '../state/use-session-draft'
import { DraftStatus } from './draft-status'
import { Icon } from './icon'
import { QuestionControl } from './question-control'

const emptyDraft: SessionDraftValues['clarification'] = { values: {}, skipped: [], message: '' }

export function ClarificationForm({ questions }: { questions: ClarificationMessage[] }) {
  const { answer, busy } = useScoutSession()
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
      className="card border border-base-300 bg-base-100 shadow-sm"
      onCompositionStart={draft.onCompositionStart}
      onCompositionEnd={draft.onCompositionEnd}
      onSubmit={(event) => {
        event.preventDefault()
        const validation = answerValidation(pending, values, skipped)
        if (validation) {
          setError(validation)
          return
        }
        const answers = collectAnswers(pending, values, skipped)
        if (!answers.length && !message.trim() && !skipped.length) {
          setError('Answer the questions, skip optional ones, or add a note.')
          return
        }
        setError('')
        void answer({ answers, message: message.trim(), skipped_question_ids: skipped })
      }}
    >
      <div className="flex items-start gap-3 border-b border-base-300 px-5 py-5 sm:px-7">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-box bg-secondary/45">
          <Icon name="sparkles" />
        </span>
        <div>
          <h2 className="text-lg font-semibold">Tell us a little more</h2>
          <p className="mt-1 text-xs leading-6 text-base-content/60">
            Answer the questions or add to or correct the information you already shared.
          </p>
        </div>
      </div>
      <fieldset
        disabled={busy || draft.status === 'loading'}
        className="min-w-0 space-y-6 p-5 sm:p-7"
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
        <div className="border-t border-base-300 pt-6">
          <label htmlFor="conversation-message" className="mb-2 block text-sm font-medium">
            Add a note or correction
          </label>
          <textarea
            id="conversation-message"
            className="textarea field-sizing-content max-h-96 min-h-24 w-full resize-none border border-base-300 bg-base-200/25 p-3 text-sm leading-6"
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
        <DraftStatus {...draft} />
        <div className="flex justify-end border-t border-base-300 pt-5">
          <button className="btn min-w-40 border-0 btn-primary" type="submit">
            Send and continue
            <Icon name="arrow" size={18} />
          </button>
        </div>
      </fieldset>
    </form>
  )
}
