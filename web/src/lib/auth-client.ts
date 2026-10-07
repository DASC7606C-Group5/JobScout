import type { AccountResponse, Credentials, PasswordChange, ModelWrite } from '../api/types.gen'
import { discardAllDrafts } from '../state/draft-navigation'
import { createApiClient } from './api-client'
import { vAccountResponse, vModelSettings, vUsage, vConnectionResult } from './api-schemas'
import { queryClient } from './query-client'

export type Account = AccountResponse

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
    request_too_large: 'The request is too large. Shorten the input and try again.',
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

const client = createApiClient('/api/v1', authenticatedFetch, (_status, data) => {
  const code =
    typeof data === 'object' &&
    data !== null &&
    'detail' in data &&
    typeof data.detail === 'object' &&
    data.detail !== null &&
    'code' in data.detail &&
    typeof data.detail.code === 'string'
      ? data.detail.code
      : 'request_failed'
  return new AccountRequestError(code)
})

export const accountClient = {
  signIn: (body: Credentials, register: boolean) =>
    client.request(
      'post',
      register ? '/api/v1/auth/register' : '/api/v1/auth/login',
      { body },
      vAccountResponse,
    ),
  changePassword: (body: PasswordChange) =>
    client.request('post', '/api/v1/auth/password', { body }),
  logout: () => client.request('post', '/api/v1/auth/logout', {}),
  models: (signal?: AbortSignal) =>
    client.request('get', '/api/v1/settings/models', signal ? { signal } : {}, vModelSettings),
  usage: (signal?: AbortSignal) =>
    client.request('get', '/api/v1/settings/usage', signal ? { signal } : {}, vUsage),
  saveModel: (role: 'semantic' | 'decision', body: ModelWrite) =>
    client.request('put', '/api/v1/settings/models/{role}', { path: { role }, body }),
  clearModel: (role: 'semantic' | 'decision') =>
    client.request('delete', '/api/v1/settings/models/{role}', { path: { role } }),
  testModel: (role: 'semantic' | 'decision') =>
    client.request(
      'post',
      '/api/v1/settings/models/{role}/test',
      { path: { role } },
      vConnectionResult,
    ),
}

export async function loadAccount(refresh = false): Promise<Account | null> {
  if (loaded && !refresh) return account
  if (loading) return loading
  loading = (async () => {
    const captured = generation
    try {
      const next = await client.request('get', '/api/v1/auth/me', {}, vAccountResponse)
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
