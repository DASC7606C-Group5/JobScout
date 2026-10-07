import { mkdir } from 'node:fs/promises'

import { expect, test, type Page } from '@playwright/test'

import type { ScoutSession } from '../../src/lib/contracts'
import { replayInput } from '../replay-scenarios'

const input = replayInput('data-analyst-internship')
const description = input.description

async function snapshot(page: Page, id: string): Promise<ScoutSession> {
  const response = await page.request.get(`/api/v1/sessions/${id}`)
  expect(response.status()).toBe(200)
  return (await response.json()) as ScoutSession
}

async function createFromForm(page: Page, complete: boolean) {
  await page.goto('/new')
  await page.getByLabel('About you', { exact: true }).fill(description)
  await page
    .getByLabel('Job interests', { exact: false })
    .fill(complete ? input.target_directions.join(', ') : '')
  await page
    .getByLabel('Work location', { exact: true })
    .fill(complete ? (input.preferences.location ?? '') : '')
  await page
    .getByLabel('Employment type', { exact: true })
    .fill(complete ? (input.preferences.employment_type ?? '') : '')
  const accepted = page.waitForResponse(
    (response) =>
      response.request().method() === 'POST' && response.url().endsWith('/api/v1/sessions'),
  )
  await page.getByRole('button', { name: 'Analyze and continue' }).click()
  const response = await accepted
  expect(response.status()).toBe(202)
  const session = (await response.json()) as ScoutSession
  expect(session).toMatchObject({ mode: 'replay', outcome: 'running', revision: 1 })
  return session.session_id
}

async function confirmAndVerifyResults(page: Page, id: string) {
  await expect(page.getByRole('button', { name: 'Confirm and search' })).toBeEnabled({
    timeout: 15_000,
  })
  const summary = await snapshot(page, id)
  expect(summary).toMatchObject({
    outcome: 'paused',
    current_stage: 'confirm',
    mode: 'replay',
    recommendation: null,
  })
  expect(summary.search_summary).toMatchObject({
    ready: true,
    confirmed: false,
    revision: summary.revision,
  })
  expect(summary.source_outcomes).toEqual([])
  await page.reload()
  await expect(page.getByRole('button', { name: 'Confirm and search' })).toBeEnabled()
  expect((await snapshot(page, id)).revision).toBe(summary.revision)
  const accepted = page.waitForResponse(
    (response) =>
      response.request().method() === 'POST' && response.url().endsWith(`/sessions/${id}/resume`),
  )
  await page.getByRole('button', { name: 'Confirm and search' }).click()
  const response = await accepted
  expect(response.status()).toBe(202)
  expect(await response.json()).toMatchObject({
    outcome: 'running',
    revision: summary.revision + 1,
    mode: 'replay',
  })
  await expect(page.getByRole('region', { name: 'Recommended jobs' })).toBeVisible({
    timeout: 20_000,
  })
  const results = await snapshot(page, id)
  expect(results).toMatchObject({
    outcome: 'completed',
    current_stage: 'completed',
    mode: 'replay',
  })
  expect(results.errors).toEqual([])
  const jobs = results.recommendation?.jobs ?? []
  expect(jobs.length).toBeGreaterThan(0)
  expect(jobs.length).toBeLessThanOrEqual(results.profile!.search_options.result_count)
  expect(new Set(jobs.map((item) => item.job.job_id)).size).toBe(jobs.length)
  expect(results.source_outcomes.some((outcome) => outcome.source === 'synthetic-replay')).toBe(
    true,
  )
  const item = jobs[0]!
  expect(item.matching_reasons.some((reason) => reason.level === 'strong')).toBe(true)
  for (const reason of item.matching_reasons) {
    for (const quote of reason.job_source_quotes) {
      const document = item.job.source_documents.find(
        (entry) => entry.document_id === quote.document_id,
      )
      expect(document?.text).toContain(quote.excerpt)
    }
    for (const quote of reason.profile_source_quotes) expect(description).toContain(quote.excerpt)
  }
  await page.getByRole('button', { name: 'View job: ' + item.job.title, exact: true }).click()
  const article = page.getByRole('article', { name: 'Job details', exact: true })
  await article.getByText('Job requirements and your background', { exact: true }).click()
  await expect(
    article.getByRole('link', { name: 'Open job listing', exact: true }).first(),
  ).toHaveAttribute(
    'href',
    item.matching_reasons.flatMap((reason) => reason.job_source_quotes)[0]!.source_url!,
  )
  const lastSupportedReason = item.matching_reasons
    .filter((reason) => reason.job_source_quotes.length || reason.profile_source_quotes.length)
    .at(-1)
  if (lastSupportedReason)
    await expect(
      article.getByRole('heading', { name: lastSupportedReason.requirement, exact: true }).last(),
    ).toBeVisible()
  if (process.env.JOBSCOUT_REVIEW_SCREENSHOTS === '1') {
    await mkdir('.tools/review', { recursive: true })
    await page.setViewportSize({ width: 1440, height: 1100 })
    await page.evaluate(() => window.scrollTo(0, 0))
    await page.evaluate(() =>
      Promise.all(document.getAnimations().map((animation) => animation.finished.catch(() => {}))),
    )
    await page.screenshot({
      path: '.tools/review/replay-results-desktop.png',
      fullPage: true,
      animations: 'disabled',
    })
    await article.getByText('Job requirements and your background', { exact: true }).click()
    await page.evaluate(() =>
      Promise.all(document.getAnimations().map((animation) => animation.finished.catch(() => {}))),
    )
    await page.evaluate(() => window.scrollTo(0, 0))
    await page.screenshot({
      path: '.tools/review/replay-results-overview.png',
      fullPage: true,
      animations: 'disabled',
    })
  }
  await page.reload()
  await expect(page.getByRole('region', { name: 'Recommended jobs' })).toBeVisible()
  expect((await snapshot(page, id)).recommendation).toEqual(results.recommendation)
  expect(await page.evaluate(() => Object.keys(sessionStorage))).toEqual([])
  expect(await page.evaluate(() => localStorage.getItem('jobscout.session_id'))).toBe(id)
}

for (const complete of [true, false]) {
  test(`real replay backend: ${complete ? 'complete input' : 'dynamic clarification'} → confirm → results with source excerpts → refresh`, async ({
    page,
  }) => {
    test.setTimeout(45_000)
    const errors: string[] = []
    page.on('pageerror', (error) => errors.push(error.message))
    page.on('console', (message) => {
      if (message.type() === 'error') errors.push(`${message.text()} ${message.location().url}`)
    })
    const id = await createFromForm(page, complete)
    try {
      if (!complete) {
        await expect(page.getByRole('checkbox', { name: 'Data Analyst', exact: true })).toBeVisible(
          {
            timeout: 15_000,
          },
        )
        await page.getByRole('checkbox', { name: 'Data Analyst', exact: true }).check()
        await page.getByRole('radio', { name: 'Hong Kong', exact: true }).check()
        await page.getByRole('radio', { name: 'Internship', exact: true }).check()
        await page.getByRole('button', { name: 'Send and continue' }).click()
      }
      await confirmAndVerifyResults(page, id)
      expect(errors).toEqual([])
    } catch (error) {
      const failure = await snapshot(page, id)
      await test.info().attach('replay-failure-snapshot', {
        body: JSON.stringify(failure, null, 2),
        contentType: 'application/json',
      })
      console.log('REPLAY_FAILURE_SNAPSHOT', JSON.stringify(failure))
      throw error
    } finally {
      expect((await page.request.delete(`/api/v1/sessions/${id}`)).status()).toBe(204)
    }
  })
}
