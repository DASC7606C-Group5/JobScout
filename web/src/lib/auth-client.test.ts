import { afterEach, expect, spyOn, test } from 'bun:test'
import { rejects } from 'node:assert/strict'

import { registerDraft } from '../state/draft-navigation'
import {
  accountClient,
  authenticatedFetch,
  changeAccount,
  currentAccount,
  loadAccount,
} from './auth-client'
import { queryClient } from './query-client'

const account = {
  user_id: 'first-student',
  username: 'first',
  csrf_token: 'synthetic-csrf',
  expires_at: '2099-01-01T00:00:00Z',
}
const originalFetch = globalThis.fetch
function mockFetch(handler: (url: RequestInfo | URL, init?: RequestInit) => Promise<Response>) {
  spyOn(globalThis, 'fetch').mockImplementation(Object.assign(handler, { preconnect: () => {} }))
}
afterEach(() => {
  globalThis.fetch = originalFetch
  changeAccount(null)
})

test('an unauthenticated response clears the account and preserves the login error', async () => {
  changeAccount(account)
  mockFetch(async () =>
    Response.json({ detail: { code: 'authentication_required' } }, { status: 401 }),
  )
  expect(await loadAccount(true)).toBeNull()
  expect(currentAccount()).toBeNull()
})

test('account changes discard private requests, query results, and pending drafts', async () => {
  changeAccount(account)
  queryClient.setQueryData(['private-search'], { description: 'Private applicant input' })
  let discarded = false
  registerDraft(
    {
      hasPending: () => true,
      flush: async () => true,
      discard: () => {
        discarded = true
      },
    },
    '/new',
  )
  let release!: () => void
  const waiting = new Promise<void>((resolve) => {
    release = resolve
  })
  mockFetch(async (_url, init) => {
    expect(new Headers(init?.headers).get('X-CSRF-Token')).toBe(account.csrf_token)
    await waiting
    return Response.json({ description: 'Private applicant input' })
  })
  const pending = authenticatedFetch('/api/v1/workspace/draft', { method: 'PUT' })
  changeAccount({ ...account, user_id: 'second-student', username: 'second' })
  release()
  await rejects(pending, { name: 'AbortError' })
  expect(queryClient.getQueryData(['private-search'])).toBeUndefined()
  expect(discarded).toBe(true)
})

test('an incorrect password does not end the current account session', async () => {
  changeAccount(account)
  mockFetch(async () => Response.json({ detail: { code: 'invalid_credentials' } }, { status: 401 }))
  await rejects(
    accountClient.changePassword({
      current_password: 'synthetic-old-password',
      new_password: 'synthetic-new-password',
    }),
    { code: 'invalid_credentials' },
  )
  expect(currentAccount()?.user_id).toBe(account.user_id)
})

test('an expired password-change session clears the current account', async () => {
  changeAccount(account)
  mockFetch(async () =>
    Response.json({ detail: { code: 'authentication_required' } }, { status: 401 }),
  )
  await rejects(
    accountClient.changePassword({
      current_password: 'synthetic-old-password',
      new_password: 'synthetic-new-password',
    }),
    { code: 'authentication_required' },
  )
  expect(currentAccount()).toBeNull()
})

test('account responses are validated before changing identity', async () => {
  changeAccount(account)
  mockFetch(async () => Response.json({ ...account, csrf_token: 42 }))
  await rejects(
    accountClient.signIn({ username: 'student', password: 'synthetic-password' }, false),
    { code: 'invalid_response' },
  )
  expect(currentAccount()?.user_id).toBe(account.user_id)
})

test('daily allowance accepts disabled development usage and rejects invalid production usage', async () => {
  mockFetch(async () => Response.json({ enabled: false }))
  expect(await accountClient.usage()).toEqual({ enabled: false })
  const usage = {
    enabled: true,
    remaining: 5,
    used: 2,
    limit: 7,
    server_remaining: 20,
    day: '2026-10-08',
    timezone: 'Asia/Hong_Kong',
  }
  mockFetch(async () => Response.json(usage))
  expect(await accountClient.usage()).toEqual(usage)
  mockFetch(async () => Response.json({ ...usage, remaining: -1 }))
  await rejects(accountClient.usage(), { code: 'invalid_response' })
})
