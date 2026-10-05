import { useState } from 'react'

import type { ClarificationMessage } from '../lib/contracts'
import { collectAnswers, pendingQuestions } from '../lib/conversation'
import { useScoutSession } from '../state/session-context'
import { QuestionControl } from './question-control'

export function ClarificationForm({ questions }: { questions: ClarificationMessage[] }) {
  const { answer, busy } = useScoutSession()
  const pending = pendingQuestions(questions)
  const [values, setValues] = useState<Record<string, string | string[]>>({})
  const [skipped, setSkipped] = useState<string[]>([])
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const skippedIds = new Set(skipped)
  return (
    <form
      className="card border border-base-300 bg-base-100 p-5 sm:p-7"
      onSubmit={(event) => {
        event.preventDefault()
        const answers = collectAnswers(pending, values, skipped)
        if (!answers.length && !message.trim() && !skipped.length) {
          setError('请回答问题、跳过选填项，或补充你的想法。')
          return
        }
        setError('')
        answer({ answers, message: message.trim(), skipped_question_ids: skipped })
      }}
    >
      <h2 className="mb-3 text-lg font-semibold">再了解你一点点</h2>
      <p className="mb-6 text-sm text-base-content/60">
        可以回答问题，也可以直接补充或纠正之前的信息。
      </p>
      <fieldset disabled={busy} className="min-w-0 space-y-6">
        {pending.map((question) => (
          <QuestionControl
            key={question.question_id}
            question={question}
            value={values[question.question_id] ?? ''}
            skipped={skippedIds.has(question.question_id)}
            onChange={(value) => setValues({ ...values, [question.question_id]: value })}
            onSkip={(checked) =>
              setSkipped(
                checked
                  ? [...skipped, question.question_id]
                  : skipped.filter((id) => id !== question.question_id),
              )
            }
          />
        ))}
        <div>
          <label htmlFor="conversation-message" className="mb-2 block text-sm font-medium">
            补充或纠正
          </label>
          <textarea
            id="conversation-message"
            className="textarea w-full"
            value={message}
            onChange={(event) => setMessage(event.target.value)}
            maxLength={10000}
            placeholder="例如：我想改为数据分析方向，接受香港或深圳。"
          />
        </div>
        {error && (
          <p role="alert" className="text-sm text-error-content">
            {error}
          </p>
        )}
        <button className="btn rounded-xl btn-primary" type="submit">
          发送并继续
        </button>
      </fieldset>
    </form>
  )
}
