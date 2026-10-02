import { useEffect, useMemo } from 'react'
import { useForm } from 'react-hook-form'

import type { ClarificationMessage } from '../lib/contracts'
import { useScoutStore } from '../state/scout-context'
import { Icon } from './icon'

type AnswerValues = { responses: { value: string }[] }

export function ClarificationForm({ questions }: { questions: ClarificationMessage[] }) {
  const store = useScoutStore()
  const pending = useMemo(
    () => questions.filter((question) => question.status === 'pending'),
    [questions],
  )
  const {
    register,
    subscribe,
    handleSubmit,
    formState: { errors },
  } = useForm<AnswerValues>({
    defaultValues: {
      responses: pending.map((question) => ({
        value: store.getState().answers[question.field] ?? '',
      })),
    },
  })
  // Use indexed fields: API field identifiers contain dots and must remain flat keys.
  function toAnswers(values: AnswerValues) {
    return Object.fromEntries(
      pending.map((question, index) => [question.field, values.responses[index]?.value ?? '']),
    )
  }
  useEffect(
    () =>
      subscribe({
        formState: { values: true },
        callback: ({ values }) =>
          store
            .getState()
            .saveAnswers(
              Object.fromEntries(
                pending.map((question, index) => [
                  question.field,
                  values.responses[index]?.value ?? '',
                ]),
              ),
            ),
      }),
    [subscribe, store, pending],
  )
  return (
    <form
      className="card border border-base-300 bg-base-100 p-5 sm:p-7"
      noValidate
      onSubmit={(event) => {
        void handleSubmit((values) => store.getState().answer(toAnswers(values)))(event)
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
              aria-describedby={`reason-${index} answer-error-${index}`}
              aria-invalid={Boolean(errors.responses?.[index]?.value)}
              {...register(`responses.${index}.value`, {
                validate: (value) =>
                  !question.required || Boolean(value.trim()) || '请填写此必填项。',
              })}
              placeholder="在这里填写你的想法"
            />
            <p
              id={`answer-error-${index}`}
              role="alert"
              className="mt-2 text-xs text-error-content"
            >
              {errors.responses?.[index]?.value?.message}
            </p>
          </div>
        ))}
      </div>
      <div className="mt-7 flex justify-end border-t border-base-300 pt-5">
        <button className="btn rounded-xl border-0 btn-primary" type="submit">
          确认并继续
          <Icon name="arrow" size={18} />
        </button>
      </div>
    </form>
  )
}
