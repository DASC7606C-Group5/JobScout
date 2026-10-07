import { ApplicantRequestError } from './applicant-errors'
import { identityEvents, loadAccount } from './auth-client'
import type { ScoutSession } from './contracts'
import { isSessionResponse } from './session-response'

export interface SessionEventHandlers {
  onSnapshot: (session: ScoutSession) => void
  onError: (error: Error) => void
}

export interface SessionEventSource {
  addEventListener: (type: 'snapshot', listener: (event: MessageEvent<string>) => void) => void
  onerror: ((event: Event) => unknown) | null
  close: () => void
}

export function subscribeToSession(
  url: string,
  sessionId: string,
  handlers: SessionEventHandlers,
  createSource: (url: string) => SessionEventSource = (url) => new EventSource(url),
) {
  const source = createSource(url)
  let closed = false
  const close = () => {
    if (closed) return
    closed = true
    source.close()
    identityEvents.removeEventListener('change', close)
  }
  identityEvents.addEventListener('change', close)
  source.addEventListener('snapshot', (event) => {
    if (closed) return
    let data: unknown
    try {
      data = JSON.parse(event.data)
    } catch {
      close()
      handlers.onError(new ApplicantRequestError('invalid_response'))
      return
    }
    if (!isSessionResponse(data) || data.session_id !== sessionId) {
      close()
      handlers.onError(new ApplicantRequestError('invalid_response'))
      return
    }
    if (data.outcome !== 'running') close()
    handlers.onSnapshot(data)
  })
  source.onerror = () => {
    if (!closed) {
      handlers.onError(new ApplicantRequestError('connection_unavailable'))
      void loadAccount(true).catch(() => {})
    }
  }
  return close
}
