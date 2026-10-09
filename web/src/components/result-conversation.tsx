import { useSearch } from '@tanstack/react-router'
import { useEffect, useId, useRef, useState } from 'react'

import type { ScoutSession } from '../lib/contracts'
import { orderResults, visibleJobs } from '../lib/result-navigation'
import { useScoutSession } from '../state/session-context'
import { AsyncButton } from './async-button'
import { ClarificationForm } from './clarification-form'
import { ConversationHistory } from './conversation-history'
import { Icon } from './icon'

function showConversation(dialog: HTMLDialogElement | null) {
  if (!dialog || dialog.open) return
  if (window.matchMedia('(min-width: 640px)').matches) dialog.show()
  else dialog.showModal()
}

export function ResultConversation({ session }: { session: ScoutSession }) {
  const { retry } = useScoutSession()
  const draft = useConversationDraft(session)
  const id = useId()
  const panel = useRef<HTMLDialogElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  const scroll = useRef<HTMLDivElement>(null)
  const [open, setOpen] = useState(false)
  const latestReply = [...session.conversation]
    .reverse()
    .find((entry) => entry.role === 'assistant')?.message_id
  const [seenReply, setSeenReply] = useState(latestReply)
  const lastMessage = session.conversation.at(-1)?.message_id
  const questionId =
    session.current_stage === 'follow_up_clarify'
      ? session.clarification_questions.find((question) => question.status === 'pending')
          ?.question_id
      : undefined
  const openedQuestion = useRef<string | undefined>(undefined)
  const unread = !open && latestReply !== seenReply

  useEffect(() => {
    if (questionId && openedQuestion.current !== questionId) {
      openedQuestion.current = questionId
      showConversation(panel.current)
    }
  }, [questionId])

  useEffect(() => {
    if (open) scroll.current?.scrollTo({ top: scroll.current.scrollHeight })
  }, [open, lastMessage, questionId])

  useEffect(() => {
    if (!open) return
    function escape(event: KeyboardEvent) {
      if (event.key === 'Escape' && !event.defaultPrevented) {
        event.preventDefault()
        panel.current?.close()
      }
    }
    window.addEventListener('keydown', escape)
    return () => window.removeEventListener('keydown', escape)
  }, [open])

  return (
    <>
      <dialog
        ref={panel}
        id={id}
        aria-label="Search conversation"
        className="peer/conversation card fixed inset-0 z-50 m-0 hidden h-dvh max-h-none w-screen max-w-none flex-col overflow-hidden rounded-none border border-base-300 bg-base-100 p-0 text-base-content shadow-xl backdrop:bg-base-content/15 open:flex sm:inset-auto sm:right-6 sm:bottom-6 sm:h-[min(38rem,calc(100dvh-3rem))] sm:w-[26rem] sm:max-w-[calc(100vw-3rem)] sm:rounded-box"
        onToggle={(event) => {
          setOpen(event.newState === 'open')
          setSeenReply(latestReply)
        }}
        onClose={() => trigger.current?.focus({ preventScroll: true })}
        onKeyDown={(event) => {
          if (event.key !== 'Tab' || !event.currentTarget.matches(':modal')) return
          const controls = [
            ...event.currentTarget.querySelectorAll<HTMLElement>(
              'button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), a[href], [tabindex="0"]',
            ),
          ].filter((element) => element.getClientRects().length > 0)
          const first = controls[0]
          const last = controls.at(-1)
          if (event.shiftKey && document.activeElement === first) {
            event.preventDefault()
            last?.focus()
          } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault()
            first?.focus()
          }
        }}
      >
        <header className="flex shrink-0 items-center justify-between gap-3 border-b border-base-300/70 px-4 py-3">
          <div className="flex items-center gap-2.5">
            <Icon name="message" size={18} className="text-base-content/65" />
            <h2 className="text-sm font-semibold">Search conversation</h2>
          </div>
          <form method="dialog">
            <button
              type="submit"
              aria-label="Close conversation panel"
              className="btn btn-square rounded-lg btn-ghost btn-sm"
            >
              <Icon name="close" size={18} />
            </button>
          </form>
        </header>
        <div ref={scroll} className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
          {session.conversation.length ? (
            <ConversationHistory session={session} embedded />
          ) : (
            <p className="p-5 text-sm leading-6 text-base-content/65">
              Ask about a job, adjust your preferences, or ask for more similar roles.
            </p>
          )}
          {questionId && (
            <div className="px-4 pb-4">
              <ClarificationForm
                key={`${session.session_id}-${session.revision}`}
                questions={session.clarification_questions}
                compact
              />
            </div>
          )}
          {session.outcome === 'running' && (
            <output className="flex items-center gap-2 px-5 pb-4 text-sm text-base-content/65">
              <span className="loading loading-xs loading-dots" aria-hidden="true" />
              {session.current_stage === 'follow_up_interpret'
                ? 'Reading your message…'
                : 'Finding and reviewing jobs…'}
            </output>
          )}
          {session.outcome === 'failed' && (
            <div className="px-5 pb-4 text-sm">
              <p className="mb-2 text-base-content/65">
                This request did not finish. Your results are still here.
              </p>
              {session.retryable && (
                <AsyncButton className="btn btn-sm" onClick={retry}>
                  Try again
                </AsyncButton>
              )}
            </div>
          )}
        </div>
        {!questionId && <ConversationComposer draft={draft} />}
      </dialog>
      <div className="fab z-40 peer-open/conversation:hidden sm:right-6 sm:bottom-6">
        <button
          ref={trigger}
          type="button"
          aria-label="Open conversation"
          aria-expanded={open}
          aria-controls={id}
          className="btn relative btn-circle border-0 bg-base-content text-base-100 shadow-md hover:bg-base-content/85"
          onClick={() => {
            draft.begin()
            showConversation(panel.current)
          }}
        >
          <Icon name="message" size={23} />
          {(unread || questionId) && (
            <span className="absolute -top-1 -right-1 badge border-base-100 bg-secondary badge-sm text-secondary-content">
              <span className="sr-only">New reply</span>1
            </span>
          )}
        </button>
      </div>
    </>
  )
}

function useConversationDraft(session: ScoutSession) {
  const { followUp, busy, pending } = useScoutSession()
  const search = useSearch({ strict: false })
  const [message, setMessage] = useState('')
  const [referenceId, setReferenceId] = useState<string | null>()
  const hidden = new Set(session.hidden_job_ids)
  const jobs = orderResults(
    [...(session.recommendation?.jobs ?? []), ...(session.recommendation?.pending_jobs ?? [])],
    session.result_order,
  )
  const eligible = jobs.filter(
    ({ job }) => hidden.has(job.job_id) === (search.visibility === 'hidden'),
  )
  const available = visibleJobs(eligible, search)
  const selected = eligible.find(({ job }) => job.job_id === search.job) ?? available[0]
  const reference = jobs.find(({ job }) => job.job_id === referenceId)?.job
  const disabled = busy || session.outcome !== 'completed'
  async function send() {
    const text = message.trim()
    if (!text || disabled) return
    const submitted = await followUp({
      action: 'message',
      job_id: referenceId ?? null,
      message: text,
    })
    if (submitted) setMessage('')
  }
  return {
    message,
    setMessage,
    referenceId,
    setReferenceId,
    selected,
    reference,
    disabled,
    pending,
    send,
    begin() {
      if (referenceId === undefined) setReferenceId(selected?.job.job_id ?? null)
    },
  }
}

function ConversationComposer({ draft }: { draft: ReturnType<typeof useConversationDraft> }) {
  const {
    message,
    setMessage,
    referenceId,
    setReferenceId,
    selected,
    reference,
    disabled,
    pending,
    send,
  } = draft
  return (
    <form
      className="shrink-0 px-4 pt-2 pb-4"
      onSubmit={(event) => {
        event.preventDefault()
        void send()
      }}
    >
      <div className="rounded-box border border-base-content/15 bg-base-100 transition-colors focus-within:border-base-content/35 focus-within:ring-2 focus-within:ring-base-content/5">
        {reference && (
          <div className="mx-3 mt-3 flex min-w-0 items-center gap-2 rounded-lg bg-base-200/65 py-1.5 pr-1.5 pl-2.5 text-xs">
            <Icon name="briefcase" size={14} className="shrink-0 text-base-content/55" />
            <span className="flex-1 truncate text-base-content/75" title={reference.title}>
              About: {reference.title}
            </span>
            <button
              type="button"
              className="btn btn-square rounded-md btn-ghost btn-xs"
              aria-label="Remove job reference"
              disabled={disabled}
              onClick={() => setReferenceId(null)}
            >
              <Icon name="close" size={13} />
            </button>
          </div>
        )}
        <textarea
          aria-label="Question or preference"
          className="textarea block field-sizing-content max-h-40 min-h-16 w-full resize-none rounded-none border-0 bg-transparent px-3.5 py-3 text-base leading-6 shadow-none outline-none focus:shadow-none focus:outline-none disabled:bg-transparent sm:text-sm"
          value={message}
          onChange={(event) => setMessage(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault()
              void send()
            }
          }}
          maxLength={10000}
          rows={2}
          disabled={disabled}
          placeholder="Ask about a job or refine your search…"
        />
        <div className="flex items-center justify-between gap-3 px-3 pb-3">
          <div className="min-w-0 text-xs text-base-content/55">
            {selected && selected.job.job_id !== referenceId ? (
              <button
                type="button"
                className="btn h-auto min-h-0 rounded-md btn-ghost px-1 py-1 text-base-content/65 btn-xs"
                disabled={disabled}
                onClick={() => setReferenceId(selected.job.job_id)}
              >
                <Icon name="plus" size={13} /> Use selected job
              </button>
            ) : (
              <span className="hidden sm:inline">Enter to send</span>
            )}
            {!reference && <span className="sr-only">About this search</span>}
          </div>
          <button
            type="submit"
            aria-label="Send message"
            className="btn btn-square shrink-0 rounded-lg border-0 bg-base-content text-base-100 shadow-none btn-sm hover:bg-base-content/85 disabled:border-0 disabled:bg-base-200 disabled:text-base-content/30 disabled:opacity-100"
            disabled={disabled || !message.trim()}
          >
            {pending ? (
              <span className="loading loading-xs loading-spinner" aria-hidden="true" />
            ) : (
              <Icon name="send" size={18} />
            )}
          </button>
        </div>
      </div>
    </form>
  )
}
