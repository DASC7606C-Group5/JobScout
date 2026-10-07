import { afterEach, expect, test } from 'bun:test'

import { changeAccount } from '../lib/auth-client'
import { queryClient } from '../lib/query-client'
import { workspaceClient } from '../lib/workspace-client'
import { getDraftController } from './draft-store'

const initial = { description: '' }
const account = {
  user_id: 'first-student',
  username: 'first',
  csrf_token: 'synthetic-csrf',
  expires_at: '2099-01-01T00:00:00Z',
}

afterEach(() => changeAccount(null))

test('switching accounts discards cached drafts even after their views unmount', () => {
  changeAccount(account)
  const first = getDraftController(queryClient, '/workspace/draft', initial, workspaceClient)
  first.hydrate({ data: { description: 'Private applicant input' }, revision: 8, updated_at: null })
  first.setComposing(true)
  first.update({ description: 'Private unsaved input' })

  changeAccount({ ...account, user_id: 'second-student', username: 'second' })
  const second = getDraftController(queryClient, '/workspace/draft', initial, workspaceClient)
  expect(first.hasPending()).toBe(false)
  expect(first.getSnapshot().value).toEqual(initial)
  expect(second).not.toBe(first)
  expect(second.getSnapshot().value).toEqual(initial)
  second.hydrate({ data: { description: 'Second applicant' }, revision: 1, updated_at: null })
  expect(second.getSnapshot().value.description).toBe('Second applicant')
  expect(second.getSnapshot().revision).toBe(1)
})

test('returning to a discarded session draft creates an editable controller', () => {
  const path = '/sessions/session-1/drafts/2/summary'
  const first = getDraftController(queryClient, path, initial, workspaceClient)
  first.discard()
  const next = getDraftController(queryClient, path, initial, workspaceClient)
  expect(next).not.toBe(first)
  next.hydrate({ data: initial, revision: 1, updated_at: null })
  next.setComposing(true)
  next.update({ description: 'Updated draft' })
  expect(next.getSnapshot().value.description).toBe('Updated draft')
  expect(next.hasPending()).toBe(true)
})
