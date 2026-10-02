import { useState } from 'react'

import type { ClarificationMessage } from '../lib/contracts'
import { Icon } from './icon'

export function ClarificationForm({
  questions,
  answers,
  onChange,
  onSubmit,
}: {
  questions: ClarificationMessage[]
  answers: Record<string, string>
  onChange: (answers: Record<string, string>) => void
  onSubmit: (answers: Record<string, string>) => void
}) {
  const [error, setError] = useState('')
  const pending = questions.filter((question) => question.status === 'pending')
  return (
    <form
      className="card border border-base-300 bg-base-100 p-5 sm:p-7"
      onSubmit={(event) => {
        event.preventDefault()
        if (pending.some((question) => question.required && !answers[question.field]?.trim())) {
          setError('请先回答所有必填问题，帮助我们明确搜索条件。')
          return
        }
        setError('')
        onSubmit(answers)
      }}
    >
      <div className="mb-6 flex items-start gap-3">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-secondary/40">
          <Icon name="sparkles" />
        </span>
        <div>
          <h2 className="text-lg font-semibold">再了解你一点点</h2>
          <p className="mt-2 text-sm leading-6 text-base-content/60">
            有 {pending.length} 项信息需要确认。补充后，我们就可以继续了。
          </p>
        </div>
      </div>
      <div className="space-y-6">
        {pending.map((question, index) => (
          <div key={question.field}>
            <label htmlFor={`answer-${index}`} className="mb-2 block text-sm font-medium">
              {question.question}
              {!question.required && (
                <span className="ml-2 text-xs text-base-content/50">选填</span>
              )}
            </label>
            <p id={`reason-${index}`} className="mb-3 text-xs leading-5 text-base-content/60">
              {question.reason}
            </p>
            <input
              id={`answer-${index}`}
              className="input w-full rounded-xl border border-base-300 bg-base-200/25"
              required={question.required}
              maxLength={500}
              aria-describedby={`reason-${index}`}
              value={answers[question.field] ?? ''}
              onChange={(event) => onChange({ ...answers, [question.field]: event.target.value })}
              placeholder="在这里填写你的想法"
            />
          </div>
        ))}
      </div>
      {error && (
        <p role="alert" className="mt-4 text-sm text-error-content">
          {error}
        </p>
      )}
      <div className="mt-7 flex justify-end border-t border-base-300 pt-5">
        <button className="btn rounded-xl border-0 btn-primary" type="submit">
          确认并继续
          <Icon name="arrow" size={18} />
        </button>
      </div>
    </form>
  )
}
