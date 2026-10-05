import type { ScoutSession } from '../lib/contracts'

export function ConversationHistory({
  session,
  collapsed = false,
}: {
  session: ScoutSession
  collapsed?: boolean
}) {
  const history = (
    <div className="space-y-4 p-5" aria-label="对话记录">
      {session.conversation.map((message) => (
        <div
          key={message.message_id}
          className={`rounded-xl p-4 ${message.role === 'user' ? 'ml-6 bg-primary/10' : 'mr-6 bg-base-200/50'}`}
        >
          <p className="mb-2 text-xs font-medium text-base-content/55">
            {message.role === 'user' ? '你' : 'JobScout 助手'}
          </p>
          <p className="text-sm leading-7 whitespace-pre-wrap">{message.text}</p>
        </div>
      ))}
      {session.clarification_questions
        .filter((question) => question.status !== 'pending')
        .map((question) => (
          <p key={question.question_id} className="text-xs leading-6 text-base-content/65">
            {question.question}：
            {question.status === 'skipped' ? '已跳过（选填）' : question.answer || '已回答'}
          </p>
        ))}
    </div>
  )
  if (
    !session.conversation.length &&
    !session.clarification_questions.some((question) => question.status !== 'pending')
  )
    return null
  return collapsed ? (
    <details className="mb-5 rounded-xl border border-base-300 bg-base-100">
      <summary className="cursor-pointer p-4 text-sm font-medium">查看对话历史</summary>
      {history}
    </details>
  ) : (
    <section className="mb-5 rounded-xl border border-base-300 bg-base-100">{history}</section>
  )
}
