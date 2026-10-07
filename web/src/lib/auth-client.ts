import { discardAllDrafts } from '../state/draft-navigation'
import { queryClient } from './query-client'

export interface Account {
  user_id: string
  username: string
  csrf_token: string
  expires_at: string
}

let account: Account | null = null
let loaded = false
let loading: Promise<Account | null> | null = null
let generation = 0
const listeners = new Set<() => void>()
const controllers = new Set<AbortController>()
export const identityEvents = new EventTarget()
const channel = typeof window === 'undefined' ? null : new BroadcastChannel('jobscout-account')

export function currentAccount() {
  return account
}

export function subscribeAccount(listener: () => void) {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

export function changeAccount(next: Account | null, broadcast = true) {
  generation += 1
  controllers.forEach((controller) => controller.abort())
  discardAllDrafts()
  void queryClient.cancelQueries()
  queryClient.clear()
  try {
    localStorage.removeItem('jobscout.session_id')
    sessionStorage.removeItem('jobscout.session_id')
  } catch {
    /* Browser storage is optional. */
  }
  account = next
  loaded = true
  loading = null
  listeners.forEach((listener) => listener())
  identityEvents.dispatchEvent(new Event('change'))
  if (broadcast) channel?.postMessage('changed')
}

channel?.addEventListener('message', () => {
  changeAccount(null, false)
  loaded = false
})

export async function authenticatedFetch(url: string, init: RequestInit = {}): Promise<Response> {
  const captured = generation
  const controller = new AbortController()
  controllers.add(controller)
  const signal = init.signal ? AbortSignal.any([init.signal, controller.signal]) : controller.signal
  const headers = new Headers(init.headers)
  if (!['GET', 'HEAD'].includes(init.method ?? 'GET') && account)
    headers.set('X-CSRF-Token', account.csrf_token)
  try {
    const received = await fetch(url, { ...init, headers, signal, credentials: 'same-origin' })
    const body = await received.arrayBuffer()
    if (captured !== generation) throw new DOMException('Account changed', 'AbortError')
    const response = new Response(received.status === 204 ? null : body, {
      status: received.status,
      statusText: received.statusText,
      headers: received.headers,
    })
    if (
      response.status === 401 &&
      !url.includes('/auth/login') &&
      !url.includes('/auth/register')
    ) {
      const rejected = (await response
        .clone()
        .json()
        .catch(() => null)) as { detail?: { code?: string } } | null
      if (rejected?.detail?.code === 'authentication_required') changeAccount(null)
    }
    return response
  } finally {
    controllers.delete(controller)
  }
}

export class AccountRequestError extends Error {
  constructor(public code: string) {
    super(accountErrorMessage(code))
  }
}

export function accountErrorMessage(code: string): string {
  const messages: Record<string, string> = {
    invalid_credentials: 'Username or password is incorrect.',
    username_unavailable: 'That username is already taken.',
    invalid_input: 'Check the fields and try again.',
    auth_rate_limited: 'Too many attempts. Try again in 15 minutes.',
    invalid_csrf_token: 'Your session changed. Reload and try again.',
    invalid_origin: 'This request is not allowed. Open the site using its configured address.',
    model_key_required: 'Provide a complete model configuration and API key.',
    personal_model_required: 'Save a personal model configuration before testing the connection.',
    invalid_model_settings: 'Choose an available service and a valid model name.',
    personal_models_unavailable: 'Personal model settings are unavailable. Contact the site owner.',
    model_auth: 'The model service rejected the API key. Update Settings and retry.',
    model_http:
      'The model service rejected the request or has no available quota. Update Settings or try again later.',
    model_output: 'The model does not support the required JSON output or tool calls.',
    model_transport: 'Could not connect to the model service.',
    model_timeout: 'The model service timed out.',
    server_daily_limit:
      'The server model daily allowance has been used. Set your own models or try tomorrow.',
    operation_capacity: 'Another operation is running. Try again after it finishes.',
  }
  return messages[code] ?? 'Could not complete the request. Please try again.'
}

export async function accountRequest<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const response = await authenticatedFetch(`/api/v1${path}`, {
    method,
    headers: {
      Accept: 'application/json',
      ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
    },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  })
  if (!response.ok) {
    const data = (await response.json().catch(() => null)) as { detail?: { code?: string } } | null
    throw new AccountRequestError(data?.detail?.code ?? 'request_failed')
  }
  return response.status === 204 ? (undefined as T) : ((await response.json()) as T)
}

export async function loadAccount(refresh = false): Promise<Account | null> {
  if (loaded && !refresh) return account
  if (loading) return loading
  loading = (async () => {
    const captured = generation
    try {
      const next = await accountRequest<Account>('/auth/me')
      if (
        typeof next.user_id !== 'string' ||
        typeof next.username !== 'string' ||
        typeof next.csrf_token !== 'string' ||
        typeof next.expires_at !== 'string'
      )
        throw new AccountRequestError('invalid_response')
      if (captured === generation) {
        if (account?.user_id !== next.user_id || account.csrf_token !== next.csrf_token)
          changeAccount(next, false)
        else {
          account = next
          loaded = true
          listeners.forEach((listener) => listener())
        }
      }
      return account
    } catch (error) {
      if (error instanceof AccountRequestError && error.code === 'authentication_required')
        return null
      throw error
    } finally {
      loading = null
    }
  })()
  return loading
}
