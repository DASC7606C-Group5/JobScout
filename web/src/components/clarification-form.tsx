import { useState } from 'react'

import type { ClarificationMessage } from '../lib/contracts'
import { answerValidation, collectAnswers, pendingQuestions } from '../lib/conversation'
import { useScoutSession } from '../state/session-context'
import { useSessionDraft, type SessionDraftValues } from '../state/use-session-draft'
import { Icon } from './icon'
import { QuestionControl } from './question-control'

const emptyDraft: SessionDraftValues['clarification'] = { values: {}, skipped: [], message: '' }

export function ClarificationForm({ questions }: { questions: ClarificationMessage[] }) {
  const { answer, busy } = useScoutSession()
  const pending = pendingQuestions(questions)
  const [{ values, skipped, message }, setDraft] = useSessionDraft('clarification', emptyDraft)
  const [error, setError] = useState('')
  const skippedIds = new Set(skipped)
  return (
    <form
      className="card border border-base-300 bg-base-100 shadow-sm"
      onSubmit={(event) => {
        event.preventDefault()
        const validation = answerValidation(pending, values, skipped)
        if (validation) {
          setError(validation)
          return
        }
        const answers = collectAnswers(pending, values, skipped)
        if (!answers.length && !message.trim() && !skipped.length) {
          setError('请回答问题、跳过选填项，或补充你的想法。')
          return
        }
        setError('')
        answer({ answers, message: message.trim(), skipped_question_ids: skipped })
      }}
    >
      <div className="flex items-start gap-3 border-b border-base-300 px-5 py-5 sm:px-7">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-secondary/45">
          <Icon name="sparkles" />
        </span>
        <div>
          <h2 className="text-lg font-semibold">再了解你一点点</h2>
          <p className="mt-1 text-xs leading-6 text-base-content/60">
            可以回答问题，也可以直接补充或纠正之前的信息。
          </p>
        </div>
      </div>
      <fieldset disabled={busy} className="min-w-0 space-y-6 p-5 sm:p-7">
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
            补充或纠正
          </label>
          <textarea
            id="conversation-message"
            className="textarea min-h-24 w-full resize-y rounded-xl border border-base-300 bg-base-200/25 p-3 text-sm leading-6"
            value={message}
            onChange={(event) =>
              setDraft((previous) => ({ ...previous, message: event.target.value }))
            }
            maxLength={10000}
            placeholder="例如：我想改为数据分析方向，接受香港或深圳。"
          />
        </div>
        {error && (
          <p role="alert" className="alert rounded-xl alert-soft text-sm alert-error">
            {error}
          </p>
        )}
        <div className="flex justify-end border-t border-base-300 pt-5">
          <button className="btn min-w-40 rounded-xl border-0 btn-primary" type="submit">
            发送并继续
            <Icon name="arrow" size={18} />
          </button>
        </div>
      </fieldset>
    </form>
  )
}
