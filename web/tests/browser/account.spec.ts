import { expect, test } from '@playwright/test'

import type { ModelSettingsResponse } from '../../src/api/types.gen'

test('drafts remain private and editable after switching accounts and signing back in', async ({
  page,
  baseURL,
}) => {
  const first = `draft-first-${Date.now()}`
  const second = `draft-second-${Date.now()}`
  const password = 'synthetic-browser-password'
  for (const username of [first, second]) {
    const response = await page.request.post('/api/v1/auth/register', {
      headers: { Origin: baseURL! },
      data: { username, password },
    })
    expect(response.status()).toBe(201)
  }

  async function signIn(username: string) {
    await page.goto('/login')
    await page.getByLabel('Username', { exact: true }).fill(username)
    await page.getByLabel(/^Password/).fill(password)
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()
    await expect(page).toHaveURL(/\/new$/)
  }

  async function saveDescription(description: string) {
    const saved = page.waitForResponse(
      (response) =>
        response.request().method() === 'PUT' &&
        response.url().endsWith('/api/v1/workspace/draft') &&
        response.ok(),
    )
    await page.getByLabel('About you', { exact: true }).fill(description)
    await saved
  }

  async function signOut() {
    // Unmount the draft view before clearing identity so cached controllers are covered.
    await page.getByRole('link', { name: 'Settings', exact: true }).click()
    await page.getByRole('button', { name: 'Sign out', exact: true }).click()
    await expect(page).toHaveURL(/\/login$/)
  }

  await signIn(first)
  await saveDescription('First applicant private draft')
  await signOut()
  await signIn(second)
  await expect(page.getByLabel('About you', { exact: true })).toHaveValue('')
  await saveDescription('Second applicant private draft')
  await signOut()
  await signIn(first)
  await expect(page.getByLabel('About you', { exact: true })).toHaveValue(
    'First applicant private draft',
  )
  await saveDescription('First applicant updated draft')
  await page.reload()
  await expect(page.getByLabel('About you', { exact: true })).toHaveValue(
    'First applicant updated draft',
  )
})

test('registration, independent model settings and sign-out protect the workspace', async ({
  page,
}) => {
  await page.goto('/new')
  await expect(page).toHaveURL(/\/login$/)
  await page.getByRole('button', { name: 'New here? Create an account' }).click()
  const username = `student-${Date.now()}`
  await page.getByLabel('Username', { exact: true }).fill(username)
  await page.getByLabel(/^Password/).fill('browser-password-123')
  await page.getByRole('button', { name: 'Create account', exact: true }).click()
  await expect(page).toHaveURL(/\/new$/)
  await page.getByRole('link', { name: 'Settings', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Settings', exact: true })).toBeVisible()
  await expect(page.getByText(`Signed in as ${username}.`)).toBeVisible()
  const semantic = page.getByRole('group', { name: 'Profile and job analysis' })
  const originalModels = (await (
    await page.request.get('/api/v1/settings/models')
  ).json()) as ModelSettingsResponse
  await expect(page.getByRole('button', { name: 'Test', exact: true })).toHaveCount(0)
  await semantic.getByLabel('Model service').selectOption('openai')
  await expect(semantic.getByRole('button', { name: 'Test', exact: true })).toBeDisabled()
  await semantic.getByLabel('Model name').fill('synthetic-personal-model')
  await semantic.getByLabel('API key').fill('synthetic-personal-key')
  await semantic.getByLabel('Thinking mode').check()
  await semantic.getByRole('button', { name: 'Save configuration' }).click()
  await expect(semantic.getByLabel('API key')).toHaveValue('')
  await expect(semantic.getByRole('button', { name: 'Test', exact: true })).toBeEnabled()
  const response = await page.request.get('/api/v1/settings/models')
  expect(response.status()).toBe(200)
  expect(await response.text()).not.toContain('synthetic-personal-key')
  const configuredModels = (await response.json()) as ModelSettingsResponse
  expect(configuredModels.roles.semantic).toMatchObject({
    personal: true,
    endpoint_id: 'openai',
    model: 'synthetic-personal-model',
    key_configured: true,
    thinking: true,
  })
  expect(configuredModels.roles.decision).toEqual(originalModels.roles.decision)
  await page.reload()
  await expect(semantic.getByLabel('Model name')).toHaveValue('synthetic-personal-model')
  await expect(semantic.getByLabel('Thinking mode')).toBeChecked()
  await semantic.getByLabel('Model service').selectOption('server')
  await expect(semantic.getByRole('button', { name: 'Test', exact: true })).toHaveCount(0)
  await semantic.getByRole('button', { name: 'Save configuration' }).click()
  await expect(semantic.getByLabel('Model name')).toHaveCount(0)
  await expect(semantic.getByRole('button', { name: 'Save configuration' })).toBeEnabled()
  const clearedModels = (await (
    await page.request.get('/api/v1/settings/models')
  ).json()) as ModelSettingsResponse
  expect(clearedModels.roles.semantic.personal).toBe(false)
  expect(clearedModels.roles.decision).toEqual(originalModels.roles.decision)
  await semantic.getByLabel('Model service').selectOption('openai')
  await expect(semantic.getByRole('button', { name: 'Test', exact: true })).toBeDisabled()
  await page.getByRole('button', { name: 'Sign out', exact: true }).click()
  await expect(page).toHaveURL(/\/login$/)
  expect((await page.request.get('/api/v1/saved-jobs')).status()).toBe(401)
  await page.goto('/settings')
  await expect(page).toHaveURL(/\/login$/)
  await page.getByLabel('Username', { exact: true }).fill(username)
  await page.getByLabel(/^Password/).fill('browser-password-123')
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page).toHaveURL(/\/new$/)
})
