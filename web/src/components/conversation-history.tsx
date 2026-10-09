import type { ConversationResponse, ScoutSession } from '../lib/contracts'
import { Icon } from './icon'

function Responses({ responses }: { responses: ConversationResponse[] }) {
  if (!responses.length) return null
  const unique = new Map(responses.map((response) => [JSON.stringify(response), response]))
  return (
    <dl className="space-y-3">
      {[...unique].map(([key, response]) => (
        <div key={key}>
          <dt className="mb-1.5 text-xs font-medium text-base-content/60">{response.label}</dt>
          <dd className="text-sm leading-6">
            {response.status === 'skipped' ? (
              <span className="badge badge-ghost text-xs badge-sm">Skipped</span>
            ) : Array.isArray(response.value) ? (
              response.value.length ? (
                <div className="flex flex-wrap gap-2">
                  {[...new Set(response.value)].map((value) => (
                    <span
                      key={value}
                      className="badge h-auto max-w-full border-base-300 bg-base-100/70 py-1 text-left text-sm whitespace-normal"
                    >
                      {value}
                    </span>
                  ))}
                </div>
              ) : (
                'Not provided'
              )
            ) : (
              <span className="whitespace-pre-wrap">{response.value || 'Not provided'}</span>
            )}
          </dd>
        </div>
      ))}
    </dl>
  )
}

export function ConversationHistory({
  session,
  collapsed = false,
  embedded = false,
}: {
  session: ScoutSession
  collapsed?: boolean
  embedded?: boolean
}) {
  const messages = session.conversation
  if (!messages.length) return null
  const history = (
    <div
      role="log"
      aria-label="Conversation history"
      className={`space-y-4 ${collapsed ? 'collapse-content px-5 sm:px-6' : 'p-5 sm:p-6'}`}
    >
      {messages.map((message) => (
        <div
          key={message.message_id}
          className={`chat min-w-0 ${message.role === 'user' ? 'chat-end' : 'chat-start'}`}
        >
          <div className="chat-header mb-1.5 text-xs font-medium text-base-content/55">
            {message.role === 'user' ? 'You' : 'JobScout assistant'}
          </div>
          <div
            className={`chat-bubble max-w-[92%] space-y-3 p-4 text-base-content shadow-none sm:max-w-[85%] ${embedded ? 'rounded-2xl before:hidden' : ''} ${message.role === 'user' ? 'bg-primary/15' : 'bg-base-200/65'}`}
          >
            {message.job_id && (
              <p className="border-b border-base-content/10 pb-2 text-xs font-medium text-base-content/70">
                About:{' '}
                {[
                  ...(session.recommendation?.jobs ?? []),
                  ...(session.recommendation?.pending_jobs ?? []),
                ].find(({ job }) => job.job_id === message.job_id)?.job.title ?? 'Referenced job'}
              </p>
            )}
            {message.text && (
              <p className="text-sm leading-7 break-words whitespace-pre-wrap">{message.text}</p>
            )}
            <Responses responses={message.responses} />
          </div>
        </div>
      ))}
    </div>
  )
  return embedded ? (
    history
  ) : collapsed ? (
    <details className="collapse-arrow collapse mb-5 border border-base-300 bg-base-100">
      <summary className="collapse-title text-sm font-semibold">View conversation history</summary>
      {history}
    </details>
  ) : (
    <section className="card mb-5 border border-base-300 bg-base-100">
      <h2 className="flex items-center gap-2 border-b border-base-300 p-5 text-sm font-semibold sm:p-6">
        <Icon name="sparkles" size={16} />
        Conversation
      </h2>
      {history}
    </section>
  )
}
