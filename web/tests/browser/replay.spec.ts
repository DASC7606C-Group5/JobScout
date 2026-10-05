import { expect, test, type Page } from '@playwright/test'

import type { ScoutSession } from '../../src/lib/contracts'

const description =
  'Education\nBachelor Computer Science\nSkills\nPython, SQL, Excel\nProjects\nPython SQL reporting dashboard'

async function snapshot(page: Page, id: string): Promise<ScoutSession> {
  const response = await page.request.get(`/api/v1/sessions/${id}`)
  expect(response.status()).toBe(200)
  return (await response.json()) as ScoutSession
}

async function createFromForm(page: Page, complete: boolean) {
  await page.goto('/')
  await page.getByLabel('个人介绍', { exact: true }).fill(description)
  if (complete) {
    await page.getByLabel('求职方向', { exact: false }).fill('Data Analyst')
    await page.getByLabel('工作地点', { exact: true }).fill('Hong Kong')
    await page.getByLabel('工作类型', { exact: true }).selectOption('internship')
  }
  const accepted = page.waitForResponse(
    (response) =>
      response.request().method() === 'POST' && response.url().endsWith('/api/v1/sessions'),
  )
  await page.getByRole('button', { name: '开始分析与对话' }).click()
  const response = await accepted
  expect(response.status()).toBe(202)
  const session = (await response.json()) as ScoutSession
  expect(session).toMatchObject({ mode: 'replay', outcome: 'running', revision: 1 })
  return session.session_id
}

async function confirmAndVerifyResults(page: Page, id: string) {
  await expect(page.getByRole('button', { name: '确认并开始搜索' })).toBeEnabled({
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
  await expect(page.getByRole('button', { name: '确认并开始搜索' })).toBeEnabled()
  expect((await snapshot(page, id)).revision).toBe(summary.revision)
  const accepted = page.waitForResponse(
    (response) =>
      response.request().method() === 'POST' && response.url().endsWith(`/sessions/${id}/resume`),
  )
  await page.getByRole('button', { name: '确认并开始搜索' }).click()
  const response = await accepted
  expect(response.status()).toBe(202)
  expect(await response.json()).toMatchObject({
    outcome: 'running',
    revision: summary.revision + 1,
    mode: 'replay',
  })
  await expect(page.getByRole('region', { name: '推荐岗位列表' })).toBeVisible({ timeout: 20_000 })
  const results = await snapshot(page, id)
  expect(results).toMatchObject({
    outcome: 'completed',
    current_stage: 'completed',
    mode: 'replay',
  })
  expect(results.errors).toEqual([])
  const jobs = results.recommendation?.jobs ?? []
  expect(jobs.length).toBeGreaterThan(0)
  expect(jobs.length).toBeLessThanOrEqual(5)
  expect(new Set(jobs.map((item) => item.job.job_id)).size).toBe(jobs.length)
  expect(results.source_outcomes.some((outcome) => outcome.source === 'synthetic-replay')).toBe(
    true,
  )
  const item = jobs[0]!
  expect(item.matching_reasons.some((reason) => reason.level === 'strong')).toBe(true)
  for (const reason of item.matching_reasons) {
    for (const evidence of reason.job_evidence) {
      const document = item.job.source_documents.find(
        (entry) => entry.document_id === evidence.document_id,
      )
      expect(document?.text).toContain(evidence.excerpt)
    }
    for (const evidence of reason.profile_evidence) expect(description).toContain(evidence.excerpt)
  }
  await expect(page.getByText('回放演示模式', { exact: false })).toBeVisible()
  const article = page
    .getByRole('article')
    .filter({ has: page.getByRole('heading', { name: item.job.title, exact: true }) })
  await article.getByText('岗位详情与准备建议', { exact: true }).click()
  await expect(article.getByRole('heading', { name: '匹配理由与证据', exact: true })).toBeVisible()
  await expect(article.getByText('个人经历依据', { exact: true }).first()).toBeVisible()
  await expect(article.getByRole('link', { name: '核对来源' }).first()).toHaveAttribute(
    'href',
    /^https?:\/\//,
  )
  await expect(
    page.locator('details').filter({ has: page.getByText('查看对话历史', { exact: true }) }),
  ).not.toHaveAttribute('open')
  await page.reload()
  await expect(page.getByRole('region', { name: '推荐岗位列表' })).toBeVisible()
  expect((await snapshot(page, id)).recommendation).toEqual(results.recommendation)
  expect(await page.evaluate(() => Object.keys(sessionStorage))).toEqual(['jobscout.session_id'])
}

for (const complete of [true, false]) {
  test(`real replay backend: ${complete ? 'complete input' : 'dynamic clarification'} → confirm → evidenced results → refresh`, async ({
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
        await expect(page.getByRole('heading', { name: '再了解你一点点' })).toBeVisible({
          timeout: 15_000,
        })
        await page.getByRole('checkbox', { name: 'Data Analyst', exact: true }).check()
        await page.getByRole('radio', { name: '香港', exact: true }).check()
        await page.getByRole('radio', { name: '实习', exact: true }).check()
        await page.getByRole('button', { name: '发送并继续' }).click()
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
