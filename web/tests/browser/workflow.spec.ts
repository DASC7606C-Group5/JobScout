import { mkdir } from 'node:fs/promises'

import { expect, test, type Page } from '@playwright/test'

import type {
  ClarificationMessage,
  DraftResponse,
  RecommendationItem,
  SaveDraftRequest,
  SessionSummary,
  ResumeSessionRequest,
  ScoutSession,
  StopSessionRequest,
  SearchOptions,
} from '../../src/lib/contracts'
import {
  createMatchScoreFixture,
  createRecommendationFixture,
  createSessionFixture,
} from '../fixtures'
import { startSessionEvents } from './session-events-server'

const eventServers: Awaited<ReturnType<typeof startSessionEvents>>[] = []
test.afterEach(async () => {
  await Promise.all(eventServers.splice(0).map((server) => server.close()))
})

test('history errors use one toast and retry stays busy until the request completes', async ({
  page,
}) => {
  const state = await mockSessions(page)
  let attempts = 0
  let failing = true
  let release!: () => void
  const gate = new Promise<void>((resolve) => {
    release = resolve
  })
  await page.route('**/api/v1/sessions?*', async (route) => {
    attempts += 1
    if (failing) {
      await route.fulfill({ status: 503, json: { detail: { code: 'service_unavailable' } } })
    } else {
      await gate
      await route.fallback()
    }
  })
  await page.goto('/new')
  const notice = page.getByRole('alert').filter({ hasText: 'Could not load your search history.' })
  await expect(notice).toBeVisible()
  await expect(notice).toHaveCount(1)
  await expect(page.locator('#workspace-sidebar').getByRole('alert')).toHaveCount(0)
  await mkdir('.tools/browser', { recursive: true })
  await page.screenshot({
    path: '.tools/browser/request-toast-desktop.png',
    fullPage: true,
    animations: 'disabled',
  })
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(page.getByRole('button', { name: 'Open sidebar', exact: true })).toBeVisible()
  await expect(notice).toBeVisible()
  await page.screenshot({
    path: '.tools/browser/request-toast-mobile.png',
    fullPage: true,
    animations: 'disabled',
  })
  const retry = notice.getByRole('button', { name: 'Try again', exact: true })
  const beforeRetry = attempts
  failing = false
  await retry.click()
  await expect(retry).toBeDisabled()
  await expect(retry).toHaveAttribute('aria-busy', 'true')
  await expect.poll(() => attempts).toBe(beforeRetry + 1)
  release()
  await expect(notice).toHaveCount(0)
  expect(state.historyRequests).toHaveLength(1)
})

test('saving and toast recovery prevent duplicate requests and retain the selected job after failure', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1000 })
  const session = resultSession()
  const state = await mockSessions(page, session)
  state.seedSession(session)
  const releases: (() => void)[] = []
  const writes: string[] = []
  await page.route('**/api/v1/saved-jobs/*', async (route) => {
    if (route.request().method() !== 'PUT') return route.fallback()
    writes.push(route.request().url())
    const attempt = writes.length
    await new Promise<void>((resolve) => {
      releases.push(resolve)
    })
    if (attempt === 1)
      await route.fulfill({
        status: 500,
        json: { detail: { code: 'service_unavailable', message: 'private-save-diagnostic' } },
      })
    else await route.fallback()
  })
  await page.goto('/searches/session-1')
  const save = page.getByRole('button', { name: 'Save job: React Engineer', exact: true })
  await save.click()
  await expect(save).toBeDisabled()
  await expect(save).toHaveAttribute('aria-busy', 'true')
  expect(writes).toHaveLength(1)
  releases[0]!()
  const notice = page.getByRole('alert')
  await expect(notice).toBeVisible()
  await expect(page.locator('#main-content').getByRole('alert')).toHaveCount(0)
  await expect(page.locator('body')).not.toContainText('private-save-diagnostic')
  await expect(save).toBeEnabled()
  const retry = notice.getByRole('button', { name: 'Retry', exact: true })
  await retry.click()
  await expect(retry).toBeDisabled()
  await expect(retry).toHaveAttribute('aria-busy', 'true')
  expect(writes).toEqual([writes[0], writes[0]])
  releases[1]!()
  await expect(
    page.getByRole('button', { name: 'Remove saved job: React Engineer', exact: true }),
  ).toBeVisible()
  await expect(notice).toHaveCount(0)
})

test('interrupted searches retain their activity view and published results', async ({ page }) => {
  const running = resultSession()
  running.outcome = 'running'
  running.current_stage = 'search'
  running.run_id = 'interrupt-run'
  running.progress.activity = [
    {
      job_id: 'activity-job',
      sequence: 1,
      title: 'Screened Engineer',
      company: 'Example',
      location: 'Hong Kong',
      status: 'reviewing',
      review_issue: null,
      exclusion_reasons: [],
      unknown_conditions: [],
      recommendation_fit: 'unknown',
    },
  ]
  const state = await mockSessions(page, running)
  state.seedSession(running)
  await page.goto('/searches/session-1')
  const activity = page.getByRole('region', { name: 'Job screening activity', exact: true })
  await expect(activity).toContainText('Screened Engineer')
  const failed = structuredClone(running)
  failed.outcome = 'failed'
  failed.current_stage = 'failed'
  failed.retryable = true
  failed.progress.sequence += 1
  failed.errors = [
    { code: 'search_interrupted', message: 'private-interruption-diagnostic', action: 'retry' },
  ]
  state.publish(failed)
  await expect(page.getByRole('alert')).toBeVisible()
  await expect(activity).toContainText('Screened Engineer')
  await expect(page.getByRole('button', { name: 'Finish search', exact: true })).toHaveCount(0)
  await expect(page.locator('#main-content').getByRole('alert')).toHaveCount(0)
  await expect(page.locator('body')).not.toContainText('private-interruption-diagnostic')
  await page.getByRole('button', { name: 'Dismiss notification', exact: true }).click()
  await page.getByRole('button', { name: 'View jobs', exact: true }).click()
  for (const item of failed.recommendation!.jobs)
    await expect(
      page.getByRole('button', { name: `View job: ${item.job.title}`, exact: true }),
    ).toBeVisible()
})

const makeQuestion = (
  question_id: string,
  control_type: ClarificationMessage['control_type'],
  required = true,
): ClarificationMessage => ({
  question_id,
  control_type,
  required,
  question: `${question_id} question`,
  reason: 'This helps refine your search criteria.',
  field: 'skills',
  status: 'pending',
  answer: null,
  options: [
    { id: 'one-id', label: 'Option one' },
    { id: 'two-id', label: 'Option two' },
  ],
})

async function mockSessions(page: Page, initial = createSessionFixture()) {
  let snapshot = structuredClone(initial)
  const sessions = new Map<string, ScoutSession>()
  const order: string[] = []
  const drafts = new Map<string, DraftResponse>()
  const saved = new Map<string, RecommendationItem>()
  const creations = new Map<string, string>()
  const draftRequests: SaveDraftRequest[] = []
  const historyRequests: URL[] = []
  const deleted: string[] = []
  let getCount = 0
  let createCount = 0
  const requests: ResumeSessionRequest[] = []
  const stopRequests: StopSessionRequest[] = []
  const createBodies: Record<string, unknown>[] = []
  let dropCreate = false
  let dropAnswer = false
  let conflict = false
  let failDraft = false
  let conflictDraft = false
  const events = await startSessionEvents((id) => sessions.get(id))
  eventServers.push(events)
  let completion: ReturnType<typeof setTimeout> | undefined
  page.on('close', () => clearTimeout(completion))
  function store(session: ScoutSession) {
    sessions.set(session.session_id, structuredClone(session))
    const index = order.indexOf(session.session_id)
    if (index >= 0) order.splice(index, 1)
    order.unshift(session.session_id)
    events.publish(session)
  }
  function summary(session: ScoutSession): SessionSummary {
    return {
      session_id: session.session_id,
      title: session.profile?.target_directions.join(', ') || 'New search',
      location: session.profile?.preferences.location || '',
      outcome: session.outcome,
      current_stage: session.current_stage,
      revision: session.revision,
      retryable: session.retryable,
      mode: session.mode,
      created_at: '2026-10-03T00:00:00Z',
      updated_at: '2026-10-06T00:00:00Z',
    }
  }
  await page.route('**/api/v1/**', async (route) => {
    const method = route.request().method()
    const url = new URL(route.request().url())
    const path = url.pathname.replace('/api/v1', '')
    if (path === '/auth/me') {
      await route.fulfill({
        json: {
          user_id: 'synthetic-browser-account',
          username: 'student',
          csrf_token: 'synthetic-csrf',
          expires_at: new Date(Date.now() + 43_200_000).toISOString(),
        },
      })
      return
    }
    if (path === '/sessions' && method === 'GET') {
      historyRequests.push(url)
      const start = Number(url.searchParams.get('cursor') || 0)
      const limit = Number(url.searchParams.get('limit') || 20)
      const items = order.slice(start, start + limit).map((id) => summary(sessions.get(id)!))
      await route.fulfill({
        json: { items, next_cursor: start + limit < order.length ? String(start + limit) : null },
      })
      return
    }
    if (path === '/workspace/draft' || path.includes('/drafts/')) {
      const draft = drafts.get(path) || { data: {}, revision: 0, updated_at: null }
      if (method === 'GET') {
        await route.fulfill({ json: draft })
        return
      }
      const body = route.request().postDataJSON() as SaveDraftRequest
      draftRequests.push(structuredClone(body))
      if (failDraft) {
        failDraft = false
        await route.abort('failed')
        return
      }
      if (conflictDraft || body.expected_revision !== draft.revision) {
        conflictDraft = false
        await route.fulfill({
          status: 409,
          json: { detail: { code: 'draft_changed', action: 'reload' } },
        })
        return
      }
      const next = {
        data: structuredClone(body.data),
        revision: draft.revision + 1,
        updated_at: '2026-10-06T00:00:00Z',
      }
      drafts.set(path, next)
      await route.fulfill({ json: next })
      return
    }
    if (path.startsWith('/saved-jobs')) {
      if (path === '/saved-jobs') {
        await route.fulfill({ json: { items: [...saved.values()] } })
        return
      }
      const id = decodeURIComponent(path.slice('/saved-jobs/'.length))
      if (method === 'DELETE') {
        saved.delete(id)
        await route.fulfill({ status: 204 })
        return
      }
      const body = route.request().postDataJSON() as {
        session_id: string
        expected_revision: number
      }
      const source = sessions.get(body.session_id)
      const item = [
        ...(source?.recommendation?.jobs ?? []),
        ...(source?.recommendation?.pending_jobs ?? []),
      ].find((entry) => entry.job.job_id === id)
      if (!item || source?.revision !== body.expected_revision) {
        await route.fulfill({
          status: 409,
          json: { detail: { code: 'search_changed', action: 'reload' } },
        })
        return
      }
      saved.set(id, structuredClone(item))
      await route.fulfill({ json: item })
      return
    }
    if (!path.startsWith('/sessions')) {
      await route.fallback()
      return
    }
    const id = path.split('/')[2]
    if (path.endsWith('/events')) {
      await route.continue({ url: `${events.origin}${url.pathname}` })
      return
    }
    if (method === 'DELETE') {
      deleted.push(id!)
      sessions.delete(id!)
      events.disconnect(id!)
      const index = order.indexOf(id!)
      if (index >= 0) order.splice(index, 1)
      for (const key of drafts.keys()) if (key.startsWith(`/sessions/${id}/`)) drafts.delete(key)
      await route.fulfill({ status: 204 })
      return
    }
    if (method === 'GET') {
      getCount += 1
      if (!sessions.has(id!)) {
        await route.fulfill({
          status: 404,
          json: { detail: { code: 'search_not_found', action: 'start_new_search' } },
        })
        return
      }
      await route.fulfill({ json: sessions.get(id!) })
      return
    }
    if (path === '/sessions') {
      createCount += 1
      const body = route.request().postDataJSON() as Record<string, unknown>
      createBodies.push(body)
      const requestId = String(body.request_id)
      let sessionId = creations.get(requestId)
      if (!sessionId) {
        sessionId = creations.size === 0 ? initial.session_id : `session-${creations.size + 1}`
        creations.set(requestId, sessionId)
        snapshot = { ...structuredClone(snapshot), session_id: sessionId }
        if (snapshot.profile && body.search_options) {
          snapshot.profile.search_options = body.search_options as SearchOptions
          if (snapshot.search_summary) snapshot.search_summary.profile = snapshot.profile
        }
        store(snapshot)
      }
      if (dropCreate) {
        dropCreate = false
        await route.abort('failed')
        return
      }
      await route.fulfill({ status: 202, json: sessions.get(sessionId) })
      return
    }
    snapshot = structuredClone(sessions.get(id!) || snapshot)
    if (path.endsWith('/stop')) {
      stopRequests.push(route.request().postDataJSON() as StopSessionRequest)
      snapshot = {
        ...snapshot,
        outcome: 'running',
        current_stage: 'review',
        progress: { ...snapshot.progress, retrieval_stopped: true },
        stop_reason: 'user_stopped',
      }
      clearTimeout(completion)
      store(snapshot)
      await route.fulfill({ json: snapshot })
      return
    }
    const body = route.request().postDataJSON() as ResumeSessionRequest
    requests.push(body)
    if (dropAnswer) {
      dropAnswer = false
      await route.abort('failed')
      return
    }
    if (conflict) {
      conflict = false
      snapshot = {
        ...snapshot,
        revision: snapshot.revision + 1,
        search_summary: snapshot.search_summary
          ? { ...snapshot.search_summary, revision: snapshot.revision + 1 }
          : null,
      }
      store(snapshot)
      await route.fulfill({
        status: 409,
        json: { detail: { code: 'search_changed', message: 'Search changed.', action: 'reload' } },
      })
      return
    }
    const revision = snapshot.revision + 1
    if (body.action === 'confirm_search') {
      const finish: ScoutSession = {
        ...snapshot,
        outcome: 'completed',
        current_stage: 'completed',
        revision,
        recommendation: {
          session_id: snapshot.session_id,
          generated_at: '2026-10-03T00:00:00Z',
          introduction: 'Review these jobs based on your confirmed criteria.',
          notices: [],
          jobs: [createRecommendationFixture()],
          pending_jobs: [],
        },
      }
      snapshot = {
        ...snapshot,
        revision,
        outcome: 'running',
        current_stage: 'search',
        run_id: `run-${revision}`,
      }
      completion = setTimeout(() => store(finish), 150)
    } else {
      const profile = structuredClone(snapshot.profile ?? createSessionFixture().profile)!
      if (body.search_options) profile.search_options = body.search_options
      for (const [key, value] of Object.entries(body.profile_updates)) {
        if (key === 'skills' && Array.isArray(value)) profile.skills = value
        if (key === 'target_directions' && Array.isArray(value)) profile.target_directions = value
        if (key === 'preferences.location' && (typeof value === 'string' || value === null))
          profile.preferences.location = value
        if (key === 'preferences.location_unrestricted' && typeof value === 'boolean')
          profile.preferences.location_unrestricted = value
      }
      snapshot = createSessionFixture({
        ...snapshot,
        profile,
        revision,
        outcome: 'paused',
        current_stage: 'confirm',
        recommendation: null,
        run_id: null,
        progress: createSessionFixture().progress,
        search_summary: { ...createSessionFixture().search_summary!, profile, revision },
        conversation: [
          ...snapshot.conversation,
          {
            message_id: `user-${revision}`,
            role: 'user',
            text: body.message || 'Answer updated.',
            responses: [],
            question_ids: [],
            created_at: '2026-10-03T00:00:00Z',
          },
        ],
        clarification_questions: snapshot.clarification_questions.map((q) => ({
          ...q,
          status: body.skipped_question_ids.includes(q.question_id) ? 'skipped' : 'answered',
          answer: String(body.answers.find((a) => a.question_id === q.question_id)?.value ?? ''),
        })),
      })
    }
    store(snapshot)
    for (const key of drafts.keys())
      if (key.startsWith(`/sessions/${id}/drafts/${body.expected_revision}/`)) drafts.delete(key)
    await route.fulfill({ status: 202, json: snapshot })
  })
  return {
    requests,
    stopRequests,
    createBodies,
    events,
    draftRequests,
    historyRequests,
    deleted,
    getCount: () => getCount,
    createCount: () => createCount,
    seedSession: store,
    readDraft: (path: string) => drafts.get(path),
    changeDraft: (path: string, data: Record<string, unknown>) => {
      const previous = drafts.get(path)
      drafts.set(path, {
        data: structuredClone(data),
        revision: (previous?.revision || 0) + 1,
        updated_at: '2026-10-06T00:00:00Z',
      })
    },
    failNextDraft: () => {
      failDraft = true
    },
    conflictNextDraft: () => {
      conflictDraft = true
    },
    dropNextCreate: () => {
      dropCreate = true
    },
    dropNextAnswer: () => {
      dropAnswer = true
    },
    conflictNext: () => {
      conflict = true
    },
    publish: store,
  }
}

async function openHistory(page: Page) {
  if (await page.getByRole('button', { name: 'Open sidebar', exact: true }).isVisible())
    await page.getByRole('button', { name: 'Open sidebar', exact: true }).click()
  const expand = page.getByRole('button', { name: 'Expand sidebar', exact: true })
  if (await expand.isVisible()) await expand.click()
}
async function returnToSearch(page: Page, id = 'session-1') {
  await openHistory(page)
  await page.locator(`[data-session-id="${id}"]`).click()
}
async function deleteSearch(page: Page, id = 'session-1') {
  await openHistory(page)
  await page
    .locator(`[data-session-id="${id}"]`)
    .locator('..')
    .getByRole('button', { name: /^Delete search:/ })
    .click()
  await page.locator('dialog').getByRole('button', { name: 'Delete search', exact: true }).click()
}

async function introduce(page: Page) {
  await page.goto('/new')
  await page
    .getByLabel('About you', { exact: true })
    .fill('Synthetic test profile: React development experience.')
  await page.getByRole('button', { name: 'Analyze and continue' }).click()
}

for (const width of [1280, 390]) {
  test(`compound list values survive keyboard entry, reload and submission at ${width}px`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width, height: 900 })
    const state = await mockSessions(page)
    await page.goto('/new')
    await page.getByLabel('About you', { exact: true }).fill('Synthetic engineering profile')
    const directions = page.locator('#directions')
    await directions.fill('Engineer, AI/ML')
    await directions.press('End')
    await directions.press('Enter')
    await directions.pressSequentially('UI/UX Designer')
    await directions.press('Enter')
    await directions.pressSequentially('Data analyst')
    await directions.press('Enter')
    await directions.pressSequentially('Product designer')
    await expect
      .poll(() => state.readDraft('/workspace/draft')?.data.directions)
      .toBe('Engineer, AI/ML\nUI/UX Designer\nData analyst\nProduct designer')
    await page.reload()
    await expect(directions).toHaveValue(
      'Engineer, AI/ML\nUI/UX Designer\nData analyst\nProduct designer',
    )
    await page.getByRole('button', { name: 'Analyze and continue' }).click()
    await expect(page.getByRole('button', { name: 'Confirm and search' })).toBeEnabled()
    expect(state.createBodies[0]?.target_directions).toEqual([
      'Engineer, AI/ML',
      'UI/UX Designer',
      'Data analyst',
      'Product designer',
    ])
    await page.getByRole('button', { name: 'Edit experience', exact: true }).click()
    await page
      .getByLabel('Education', { exact: true })
      .fill('BSc, Computer Science\nHigher Diploma; with distinction')
    await page
      .getByLabel('Skills', { exact: true })
      .fill('CI/CD | deployment\nStatistics, research methods')
    await page.getByRole('button', { name: 'Update criteria' }).click()
    await expect(page.getByRole('button', { name: 'Confirm and search' })).toBeEnabled()
    expect(state.requests.at(-1)?.profile_updates).toEqual({
      education: ['BSc, Computer Science', 'Higher Diploma; with distinction'],
      skills: ['CI/CD | deployment', 'Statistics, research methods'],
    })
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true)
    await page.screenshot({ path: testInfo.outputPath('compound-inputs.png'), fullPage: true })
  })
}

test('count keyboard controls preserve the chosen target through drafts, creation and confirmation edits', async ({
  page,
}) => {
  const state = await mockSessions(page)
  await page.goto('/new')
  await page.getByLabel('About you', { exact: true }).fill('Synthetic React developer')
  const number = page.getByRole('slider', { name: 'Jobs to show', exact: true })
  await number.press('Home')
  await number.press('ArrowLeft')
  await expect(number).toHaveValue('5')
  await number.press('ArrowUp')
  await expect(number).toHaveValue('6')
  await number.press('End')
  await number.press('ArrowRight')
  await expect(number).toHaveValue('20')
  await page.getByLabel('Work location', { exact: true }).fill('上海或深圳，排除浦东')
  await page
    .getByLabel('Employment type', { exact: true })
    .fill('Full-time or internship, excluding contract')
  await page.getByRole('button', { name: 'Analyze and continue' }).click()
  await expect(page.getByRole('button', { name: 'Confirm and search' })).toBeEnabled()
  expect(state.createBodies[0]).toMatchObject({
    search_options: { result_count: 20 },
    preferences: {
      location: '上海或深圳，排除浦东',
      employment_type: 'Full-time or internship, excluding contract',
    },
  })
  await page.getByRole('button', { name: 'Edit other preferences', exact: true }).click()
  await expect(number).toHaveValue('20')
  await number.press('Home')
  for (let index = 0; index < 5; index++) await number.press('ArrowRight')
  await expect(page.getByRole('button', { name: 'Confirm and search' })).toHaveCount(0)
  await page.getByRole('button', { name: 'Update criteria' }).click()
  await expect(page.getByRole('button', { name: 'Confirm and search' })).toBeEnabled()
  expect(state.requests.at(-1)).toMatchObject({
    action: 'edit_conditions',
    search_options: { result_count: 10 },
    profile_updates: {},
  })
  await page.getByRole('button', { name: 'Edit other preferences', exact: true }).click()
  await expect(number).toHaveValue('10')
})

test('composite conditions retain the entered text and keep excluded districts visible for confirmation', async ({
  page,
}) => {
  const session = createSessionFixture()
  const preferences = session.profile!.preferences
  preferences.location = '香港或深圳，排除南山区'
  const hongKong = preferences.locations.included[0]!
  preferences.locations.included.push({
    ...hongKong,
    id: 'cn:shenzhen',
    name: '深圳',
    region: 'cn',
    level: 'city',
  })
  preferences.locations.excluded = [
    {
      ...hongKong,
      id: 'cn:nanshan',
      name: '南山区',
      region: 'cn',
      level: 'district',
      parent_id: 'cn:shenzhen',
    },
  ]
  preferences.employment.included = ['full-time', 'internship']
  const state = await mockSessions(page, session)
  state.seedSession(session)
  await page.goto('/searches/session-1')
  await expect(page.getByRole('definition').filter({ hasText: 'Hong Kong, 深圳' })).toBeVisible()
  await expect(page.getByText('Excluded: 南山区', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Edit search conditions', exact: true }).click()
  await expect(page.getByLabel('Work location', { exact: true })).toHaveValue(preferences.location)
  await page.getByLabel('Work location', { exact: true }).fill('仅深圳')
  await expect(page.getByRole('button', { name: 'Confirm and search', exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: 'Update criteria', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Confirm and search' })).toBeEnabled()
  expect(state.requests.at(-1)?.profile_updates).toEqual({ 'preferences.location': '仅深圳' })
})

test('ending retrieval preserves results and continues reviewing jobs on a narrow screen', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 })
  const matched = createRecommendationFixture()
  const pending = createRecommendationFixture()
  pending.review_status = 'queued'
  pending.verification_status = 'pending'
  pending.unknown_conditions = ['location']
  pending.job = { ...pending.job, job_id: 'pending-job', title: 'Pending Engineer' }
  pending.notices = [
    {
      code: 'preference_unverified',
      scope: 'job',
      job_id: 'pending-job',
      source: null,
      preference: 'location',
      action: 'open_listing',
      message: 'Check the work location in the listing before applying.',
    },
  ]
  const running = createSessionFixture({
    outcome: 'running',
    current_stage: 'search',
    run_id: 'active-run',
    revision: 4,
    progress: {
      sequence: 3,
      discovered_count: 3,
      analyzed_count: 2,
      matched_count: 1,
      pending_count: 1,
      elapsed_seconds: 28,
      retrieval_stopped: false,
      activity: [
        {
          job_id: matched.job.job_id,
          sequence: 3,
          title: matched.job.title,
          company: matched.job.company,
          location: matched.job.location,
          status: 'reviewed',
          review_issue: null,
          exclusion_reasons: [],
          unknown_conditions: [],
          recommendation_fit: matched.recommendation_fit,
        },
        {
          job_id: pending.job.job_id,
          sequence: 2,
          title: pending.job.title,
          company: pending.job.company,
          location: pending.job.location,
          status: 'found',
          review_issue: null,
          exclusion_reasons: [],
          unknown_conditions: [],
          recommendation_fit: 'unknown',
        },
      ],
      events: [
        {
          sequence: 3,
          action: 'fetch_job_details',
          message: 'private-agent-detail: fetch_job_details candidate budget=60',
          source: 'private-source-id',
        },
      ],
    },
    recommendation: {
      session_id: 'session-1',
      generated_at: '2026-10-06T00:00:00Z',
      jobs: [matched],
      pending_jobs: [pending],
      introduction: '',
      notices: [],
    },
  })
  const state = await mockSessions(page, running)
  state.seedSession(running)
  await page.goto('/searches/session-1')
  const stop = page.getByRole('button', { name: 'Finish search', exact: true })
  await expect(stop).toBeEnabled()
  await expect(page.getByRole('region', { name: 'Job screening activity' })).toBeVisible()
  await page.getByRole('button', { name: 'View jobs so far', exact: true }).click()
  await expect(page.getByRole('button', { name: 'View job: React Engineer' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'View job: Pending Engineer' })).toBeVisible()
  await page.getByRole('button', { name: 'View job: Pending Engineer' }).click()
  await expect(page.getByRole('link', { name: 'View job listing', exact: true })).toHaveAttribute(
    'href',
    pending.job.source_url,
  )
  await page.getByRole('button', { name: 'Back to jobs' }).click()
  await expect(page.locator('body')).not.toContainText('private-agent-detail')
  await expect(page.locator('body')).not.toContainText('private-source-id')
  await mkdir('.tools/browser', { recursive: true })
  await page.screenshot({ path: '.tools/browser/agent-running-mobile.png', fullPage: true })
  await stop.focus()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('button', { name: 'View job: React Engineer' })).toBeVisible()
  expect(state.stopRequests).toHaveLength(1)
  expect(state.stopRequests[0]).toMatchObject({ expected_revision: 4, run_id: 'active-run' })
  expect(state.stopRequests[0]?.request_id).toBeTruthy()
  await expect(page.getByRole('button', { name: 'Finishing…', exact: true })).toBeDisabled()
  const reads = state.getCount()
  const finished = structuredClone(running)
  finished.outcome = 'completed'
  finished.current_stage = 'completed'
  finished.stop_reason = 'user_stopped'
  finished.progress = { ...finished.progress, sequence: 4, retrieval_stopped: true }
  finished.recommendation!.pending_jobs[0]!.review_status = 'reviewed'
  state.publish(finished)
  const pendingCard = page
    .getByRole('article')
    .filter({ has: page.getByRole('button', { name: 'View job: Pending Engineer', exact: true }) })
  await expect(
    pendingCard.getByRole('button', { name: 'Needs checking', exact: true }),
  ).toBeVisible()
  expect(state.getCount()).toBe(reads)
  await page.getByRole('button', { name: 'View job: Pending Engineer' }).click()
  await expect(page).toHaveURL(/job=pending-job/)
  await expect(page.getByRole('heading', { name: 'Pending Engineer', exact: true })).toBeVisible()
  await expect(page.getByText(pending.notices[0]!.message, { exact: true })).toHaveCount(1)
  await page.screenshot({ path: '.tools/browser/agent-pending-mobile.png', fullPage: true })
  await page.getByRole('button', { name: 'Save job: Pending Engineer', exact: true }).click()
  await expect(
    page.getByRole('button', { name: 'Remove saved job: Pending Engineer', exact: true }),
  ).toBeVisible()
  await page.getByRole('button', { name: 'Open sidebar', exact: true }).click()
  await page.getByRole('link', { name: 'Saved jobs', exact: true }).click()
  await page.getByRole('button', { name: 'View job: Pending Engineer', exact: true }).click()
  await expect(page.getByText(pending.notices[0]!.message, { exact: true })).toHaveCount(1)
  await page.reload()
  await expect(page.getByText(pending.notices[0]!.message, { exact: true })).toBeVisible()
  await page.setViewportSize({ width: 1440, height: 900 })
  await expect(page.getByRole('button', { name: 'View job: Pending Engineer' })).toBeVisible()
  await page.screenshot({ path: '.tools/browser/agent-pending-saved-desktop.png', fullPage: true })
})

test('final results preserve an open job and saved selection from an early preview', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1000 })
  const jobs = Array.from({ length: 5 }, (_, index) => {
    const row = createRecommendationFixture()
    row.job = { ...row.job, job_id: `shortlist-${index}`, title: `Engineer ${index}` }
    return row
  })
  const running = createSessionFixture({
    outcome: 'running',
    current_stage: 'search',
    run_id: 'shortlist-run',
    revision: 4,
    recommendation: {
      session_id: 'session-1',
      generated_at: '2026-10-06T00:00:00Z',
      jobs,
      pending_jobs: [],
      introduction: '',
      notices: [],
    },
  })
  running.profile!.search_options.result_count = 5
  running.progress = {
    ...running.progress,
    discovered_count: 30,
    matched_count: 5,
    analyzed_count: 23,
    activity: jobs.map((item) => ({
      sequence: 1,
      job_id: item.job.job_id,
      title: item.job.title,
      company: item.job.company,
      location: item.job.location,
      status: 'reviewed',
      review_issue: null,
      exclusion_reasons: [],
      unknown_conditions: [],
      recommendation_fit: item.recommendation_fit,
    })),
  }
  const state = await mockSessions(page, running)
  state.seedSession(running)
  await page.goto('/searches/session-1')
  await expect(page.getByRole('region', { name: 'Job screening activity' })).toBeVisible()
  await expect(page.getByRole('region', { name: 'Recommended jobs' })).toHaveCount(0)
  await mkdir('.tools/browser', { recursive: true })
  await page.screenshot({
    path: '.tools/browser/shortlist-icon-summary-desktop.png',
    fullPage: true,
    animations: 'disabled',
  })
  await page.setViewportSize({ width: 390, height: 844 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  )
  await page.screenshot({
    path: '.tools/browser/shortlist-icon-summary-mobile.png',
    fullPage: true,
    animations: 'disabled',
  })
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.getByRole('button', { name: 'View jobs so far', exact: true }).click()
  await page.getByRole('button', { name: 'View job: Engineer 0', exact: true }).click()
  await page.getByRole('button', { name: 'Save job: Engineer 0', exact: true }).click()
  await expect(
    page.getByRole('button', { name: 'Remove saved job: Engineer 0', exact: true }),
  ).toBeVisible()
  const improved = structuredClone(running)
  const better = createRecommendationFixture()
  better.job = { ...better.job, job_id: 'better-engineer', title: 'Better Engineer' }
  improved.recommendation!.jobs = [better, ...improved.recommendation!.jobs.slice(1)]
  improved.progress.analyzed_count = 26
  state.publish(improved)
  await expect(
    page.getByRole('button', { name: 'View job: Better Engineer', exact: true }),
  ).toHaveCount(0)
  await expect(
    page.getByRole('button', { name: 'View job: Engineer 0', exact: true }),
  ).toBeVisible()
  await expect(
    page.getByRole('heading', { name: 'Engineer 0', exact: true, level: 2 }),
  ).toBeVisible()
  const finished = structuredClone(improved)
  finished.outcome = 'completed'
  finished.current_stage = 'completed'
  finished.stop_reason = 'results_ready'
  state.publish(finished)
  await expect(
    page.getByRole('button', { name: 'View job: Better Engineer', exact: true }),
  ).toBeVisible()
  await expect(page.getByRole('button', { name: 'View job: Engineer 0', exact: true })).toHaveCount(
    0,
  )
  await expect(
    page.getByRole('heading', { name: 'Engineer 0', exact: true, level: 2 }),
  ).toBeVisible()
  await expect(page).toHaveURL(/job=shortlist-0/)
  await expect(
    page.getByRole('button', { name: 'Remove saved job: Engineer 0', exact: true }),
  ).toBeVisible()
  await expect(page.getByRole('button', { name: 'Finish search', exact: true })).toHaveCount(0)
  await mkdir('.tools/browser', { recursive: true })
  await page.screenshot({
    path: '.tools/browser/shortlist-results-first-desktop.png',
    fullPage: true,
  })
})

test('screening activity archives rejected jobs and automatically reveals completed matches', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 })
  const item = createRecommendationFixture()
  const running = createSessionFixture({
    outcome: 'running',
    current_stage: 'search',
    run_id: 'flow-run',
    recommendation: resultSession().recommendation,
  })
  running.progress.activity = [
    {
      job_id: item.job.job_id,
      title: item.job.title,
      company: item.job.company,
      location: item.job.location,
      status: 'reviewing',
      review_issue: null,
      exclusion_reasons: [],
      unknown_conditions: [],
      sequence: 1,
      recommendation_fit: 'unknown',
    },
    {
      job_id: 'excluded-role',
      sequence: 1,
      title: 'Another role',
      company: 'Example employer',
      location: 'Hong Kong',
      status: 'found',
      review_issue: null,
      exclusion_reasons: [],
      unknown_conditions: [],
      recommendation_fit: 'unknown',
    },
  ]
  running.progress.activity.splice(
    1,
    0,
    ...Array.from({ length: 5 }, (_, index) => ({
      job_id: `waiting-${index}`,
      sequence: 1,
      title: `Queued role ${index}`,
      company: 'Example employer',
      location: 'Hong Kong',
      status: 'found' as const,
      review_issue: null,
      exclusion_reasons: [],
      unknown_conditions: [],
      recommendation_fit: 'unknown' as const,
    })),
  )
  const state = await mockSessions(page, running)
  state.seedSession(running)
  await page.goto('/searches/session-1')
  const recent = page.getByRole('list', { name: 'Recent jobs', exact: true })
  await expect(recent.locator('[data-job-id="excluded-role"]')).toHaveAttribute(
    'data-status',
    'found',
  )
  await expect(recent.locator(`[data-job-id="${item.job.job_id}"]`)).toHaveCount(0)
  await expect(page.getByRole('region', { name: 'Recommended jobs', exact: true })).toHaveCount(0)
  const reviewed = structuredClone(running)
  reviewed.progress.sequence = 2
  reviewed.progress.activity[0]!.status = 'reviewed'
  reviewed.progress.activity[0]!.sequence = 2
  reviewed.progress.activity[0]!.recommendation_fit = 'recommended'
  reviewed.progress.activity[6]!.status = 'excluded'
  reviewed.progress.activity[6]!.sequence = 2
  state.publish(reviewed)
  await expect(recent.locator('[data-job-id="excluded-role"]')).toHaveAttribute(
    'data-status',
    'excluded',
  )
  await expect(recent.locator(`[data-job-id="${item.job.job_id}"]`)).toHaveAttribute(
    'data-status',
    'reviewed',
  )
  await mkdir('.tools/browser', { recursive: true })
  await page.screenshot({ path: '.tools/browser/search-flow-mobile.png', fullPage: true })
  await expect(recent.locator('[data-job-id="excluded-role"]')).toHaveCount(0)
  await page.locator('summary').filter({ hasText: 'Earlier activity' }).click()
  await expect(
    page
      .getByRole('list', { name: 'Earlier jobs', exact: true })
      .locator('[data-job-id="excluded-role"]'),
  ).toHaveAttribute('data-status', 'excluded')
  const completed = structuredClone(reviewed)
  completed.outcome = 'completed'
  completed.current_stage = 'completed'
  state.publish(completed)
  await expect(
    page.getByRole('button', { name: 'View job: React Engineer', exact: true }),
  ).toBeVisible()
  await expect(page.getByRole('region', { name: 'Job screening activity' })).toHaveCount(0)
  await page.getByRole('button', { name: 'View search activity', exact: true }).click()
  await expect(page.getByRole('region', { name: 'Job screening activity' })).toBeVisible()
  await page.getByRole('button', { name: 'View jobs', exact: true }).click()
  await expect(
    page.getByRole('button', { name: 'View job: React Engineer', exact: true }),
  ).toBeVisible()
  await page.reload()
  await expect(
    page.getByRole('button', { name: 'View job: React Engineer', exact: true }),
  ).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  )
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.screenshot({
    path: '.tools/browser/search-flow-final-desktop.png',
    fullPage: true,
    animations: 'disabled',
  })
})

test('summary-only advice remains readable without a numeric assessment on desktop and mobile', async ({
  page,
}) => {
  const item = createRecommendationFixture()
  item.analysis_status = 'partial'
  item.job.description_is_excerpt = true
  item.match_score = null
  item.matching_reasons = []
  item.preparation_suggestions = []
  item.recommendation_reason =
    'Your React project makes this role worth exploring. Confirm the daily duties and seniority before deciding to apply.'
  const session = resultSession()
  session.recommendation!.jobs = [item]
  session.recommendation!.pending_jobs = []
  const state = await mockSessions(page, session)
  state.seedSession(session)
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.goto('/searches/session-1')
  await page.getByRole('button', { name: 'View job: React Engineer' }).click()
  const detail = page.getByRole('article', { name: 'Job details' })
  await expect(detail).toContainText(item.recommendation_reason)
  await expect(detail.getByRole('figure')).toHaveCount(0)
  await expect(detail.getByText('Summary reviewed', { exact: true })).toBeVisible()
  await mkdir('.tools/browser', { recursive: true })
  await page.screenshot({
    path: '.tools/browser/summary-advice-desktop.png',
    fullPage: true,
    animations: 'disabled',
  })
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(detail).toContainText(item.recommendation_reason)
  await expect(detail).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  )
  await page.screenshot({
    path: '.tools/browser/summary-advice-mobile.png',
    fullPage: true,
    animations: 'disabled',
  })
})

test('partially analyzed jobs stay useful without inventing an unknown search condition', async ({
  page,
}) => {
  const partial = createRecommendationFixture()
  partial.verification_status = 'pending'
  partial.analysis_status = 'partial'
  partial.unknown_conditions = []
  partial.notices = [
    {
      code: 'analysis_partial',
      scope: 'job',
      job_id: partial.job.job_id,
      source: null,
      preference: null,
      action: 'open_listing',
      message: 'Some requirements still need a closer look. Read the full listing before applying.',
    },
  ]
  const session = resultSession()
  session.recommendation!.jobs = []
  session.recommendation!.pending_jobs = [partial]
  const state = await mockSessions(page, session)
  state.seedSession(session)
  await page.goto('/searches/session-1')
  await page.getByRole('button', { name: 'View job: React Engineer' }).click()
  const details = page.getByRole('article', { name: 'Job details' })
  await expect(details).toContainText(partial.recommendation_reason)
  await expect(details.getByText(partial.notices[0]!.message, { exact: true })).toHaveCount(1)
  await expect(page.locator('body')).not.toContainText('some search conditions')
  await expect(page.locator('body')).not.toContainText('0 jobs to explore')
})

for (const stage of ['search', 'review'] as const) {
  test(`edit criteria interrupts ${stage} and preserves the same session`, async ({ page }) => {
    if (stage === 'review') await page.setViewportSize({ width: 390, height: 844 })
    const running = createSessionFixture({
      outcome: 'running',
      current_stage: stage,
      revision: 4,
      run_id: 'active-run',
      progress: { ...createSessionFixture().progress, retrieval_stopped: stage === 'review' },
      recommendation: resultSession().recommendation,
    })
    const state = await mockSessions(page, running)
    state.seedSession(running)
    await page.goto('/searches/session-1')
    const edit = page.getByRole('button', { name: 'Edit criteria', exact: true })
    await expect(edit).toBeEnabled()
    if (stage === 'review') await edit.press('Enter')
    else await edit.click()
    await page.getByRole('button', { name: 'Edit search conditions', exact: true }).click()
    await expect(page.getByLabel('Job interests', { exact: true })).toHaveValue(
      running.profile!.target_directions.join('\n'),
    )
    await expect(page.getByLabel('Work location', { exact: true })).toHaveValue(
      running.profile!.preferences.location!,
    )
    await expect(page.getByRole('button', { name: 'Confirm and search' })).toBeEnabled()
    await expect(page.getByRole('button', { name: 'View job: React Engineer' })).toHaveCount(0)
    await expect(page).toHaveURL('/searches/session-1')
    expect(state.requests).toHaveLength(1)
    expect(state.requests[0]).toMatchObject({ action: 'edit_conditions', expected_revision: 4 })
    expect(state.createCount()).toBe(0)
    const pollCount = state.getCount()
    await page.waitForTimeout(1300)
    expect(state.getCount()).toBe(pollCount)
  })
}

test('three-step flow uses IDs, explicit confirmation, source excerpts, saved jobs and same-session edits', async ({
  page,
}) => {
  const state = await mockSessions(
    page,
    createSessionFixture({
      current_stage: 'clarify',
      search_summary: null,
      clarification_questions: [
        makeQuestion('single', 'single_choice'),
        makeQuestion('multiple', 'multiple_choice'),
        makeQuestion('optional', 'text', false),
        makeQuestion('hidden', 'text'),
      ],
    }),
  )
  await introduce(page)
  await expect(page.getByLabel('hidden question', { exact: true })).toHaveCount(0)
  const firstChoice = page.getByRole('radio', { name: 'Option one' })
  await expect(firstChoice).toBeEnabled()
  await firstChoice.press('Space')
  await expect(firstChoice).toBeChecked()
  await page.getByRole('checkbox', { name: 'Option one', exact: true }).check()
  await page.getByRole('checkbox', { name: 'Option two', exact: true }).check()
  await page.getByRole('checkbox', { name: 'Skip this question' }).check()
  await page
    .getByLabel('Add a note or correction', { exact: true })
    .fill('Correction: I’m open to any location.')
  await page.getByRole('button', { name: 'Send and continue' }).click()
  await expect(
    page.getByRole('heading', { name: 'Review your profile and search criteria' }),
  ).toBeVisible()
  expect(state.requests[0]).toMatchObject({
    action: 'answer',
    expected_revision: 1,
    answers: [
      { question_id: 'single', value: 'one-id' },
      { question_id: 'multiple', value: ['one-id', 'two-id'] },
    ],
    skipped_question_ids: ['optional'],
    message: 'Correction: I’m open to any location.',
  })
  expect(state.requests.some((request) => request.action === 'confirm_search')).toBe(false)
  await page.getByRole('button', { name: 'Edit experience', exact: true }).click()
  await page.getByLabel('Skills', { exact: true }).fill('React\nTypeScript')
  await expect(page.getByRole('button', { name: 'Confirm and search' })).toHaveCount(0)
  await page.getByRole('button', { name: 'Update criteria' }).click()
  await expect(page.getByRole('button', { name: 'Confirm and search' })).toBeEnabled()
  expect(state.requests[1]?.profile_updates).toEqual({ skills: ['React', 'TypeScript'] })
  await page.getByRole('button', { name: 'Confirm and search' }).click()
  await expect(page.getByRole('button', { name: 'View job: React Engineer' })).toBeVisible()
  expect(state.getCount()).toBe(0)
  const count = state.getCount()
  await page.waitForTimeout(1300)
  expect(state.getCount()).toBe(count)
  await page.getByRole('button', { name: 'View job: React Engineer' }).click()
  await page.getByText('Job requirements and your background', { exact: true }).click()
  await expect(page.getByText('“React development experience required.”')).toBeVisible()
  await page.getByRole('button', { name: 'Save job: React Engineer', exact: true }).click()
  await page.getByRole('link', { name: 'Saved jobs', exact: false }).first().click()
  await expect(page.getByRole('button', { name: 'View job: React Engineer' })).toBeVisible()
  await returnToSearch(page)
  await page
    .getByRole('region', { name: 'Search criteria', exact: true })
    .getByRole('button', { name: 'Edit criteria', exact: true })
    .click()
  await expect(
    page.getByRole('heading', { name: 'Review your profile and search criteria' }),
  ).toBeVisible()
  await expect(page.getByRole('button', { name: 'View job: React Engineer' })).toHaveCount(0)
  expect(state.createCount()).toBe(1)
  expect(state.requests.at(-1)?.action).toBe('edit_conditions')
  const storage = await page.evaluate(() => ({
    local: Object.fromEntries(
      Object.keys(localStorage).map((key) => [key, localStorage.getItem(key)]),
    ),
    session: Object.fromEntries(
      Object.keys(sessionStorage).map((key) => [key, sessionStorage.getItem(key)]),
    ),
  }))
  expect(storage.session).toEqual({})
  expect(storage.local).toEqual({
    'jobscout.session_id.synthetic-browser-account': 'session-1',
    'jobscout.sidebar-expanded': 'true',
  })
})

test('network retry reuses create request ID; 409 refreshes instead of replaying stale changes', async ({
  page,
}) => {
  const state = await mockSessions(page)
  state.dropNextCreate()
  await introduce(page)
  await page.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Confirm and search' })).toBeEnabled()
  expect(state.createBodies[0]?.request_id).toBe(state.createBodies[1]?.request_id)
  state.conflictNext()
  await page.getByRole('button', { name: 'Confirm and search' }).click()
  await expect.poll(state.getCount).toBe(1)
  await expect(page.getByRole('button', { name: 'Confirm and search' })).toBeEnabled()
  await page.getByRole('button', { name: 'Confirm and search' }).click()
  await expect(page.getByRole('button', { name: 'View job: React Engineer' })).toBeVisible()
  expect(state.requests[1]?.expected_revision).toBe(2)
  expect(state.requests[1]?.request_id).not.toBe(state.requests[0]?.request_id)
})

test('SSE reconnects to current progress without polling and closes on navigation and completion', async ({
  page,
}) => {
  const running = createSessionFixture({
    outcome: 'running',
    current_stage: 'search',
    run_id: 'run-sse',
  })
  running.progress.activity = [
    {
      sequence: 1,
      job_id: 'sse-candidate',
      title: 'Streamed role',
      company: 'Example',
      location: 'Remote',
      status: 'found',
      review_issue: null,
      exclusion_reasons: [],
      unknown_conditions: [],
      recommendation_fit: 'unknown',
    },
  ]
  const state = await mockSessions(page, running)
  state.seedSession(running)
  await page.goto('/searches/session-1')
  const row = page.locator('[data-job-id="sse-candidate"]')
  await expect(row).toHaveAttribute('data-status', 'found')
  await expect.poll(state.events.active).toBe(1)
  const reads = state.getCount()
  const reviewed = structuredClone(running)
  reviewed.progress.sequence = 2
  reviewed.progress.activity[0]!.sequence = 2
  reviewed.progress.activity[0]!.status = 'reviewing'
  state.publish(reviewed)
  await expect(row).toHaveAttribute('data-status', 'reviewing')
  await page.waitForTimeout(1300)
  expect(state.getCount()).toBe(reads)
  const connected = state.events.connections.length
  state.events.disconnect('session-1')
  reviewed.progress.sequence = 3
  reviewed.progress.activity[0]!.status = 'reviewed'
  reviewed.progress.activity[0]!.recommendation_fit = 'recommended'
  state.publish(reviewed)
  await expect.poll(() => state.events.connections.length).toBeGreaterThan(connected)
  await expect(row).toHaveAttribute('data-status', 'reviewed')
  await expect(page.getByRole('alert')).toHaveCount(0)
  await page.getByRole('link', { name: 'Saved jobs', exact: false }).first().click()
  await expect.poll(state.events.active).toBe(0)
  await returnToSearch(page)
  await expect.poll(state.events.active).toBe(1)
  const final = {
    ...reviewed,
    outcome: 'completed' as const,
    current_stage: 'completed',
    recommendation: resultSession().recommendation,
  }
  state.publish(final)
  await expect(page.getByRole('button', { name: 'View job: React Engineer' })).toBeVisible()
  await expect.poll(state.events.active).toBe(0)
  const connections = state.events.connections.length
  await page.waitForTimeout(400)
  expect(state.events.connections.length).toBe(connections)
})

test('reload recovers the stream by ID and delete prevents restoration', async ({ page }) => {
  const state = await mockSessions(
    page,
    createSessionFixture({ outcome: 'running', current_stage: 'extract' }),
  )
  await introduce(page)
  await expect(page.getByRole('heading', { name: 'Reviewing your experience' })).toBeVisible()
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Reviewing your experience' })).toBeVisible()
  expect(state.createCount()).toBe(1)
  await expect.poll(state.events.active).toBe(1)
  const reads = state.getCount()
  await page.waitForTimeout(1300)
  expect(state.getCount()).toBe(reads)
  await deleteSearch(page)
  await expect(page.getByRole('button', { name: 'Analyze and continue' })).toBeVisible()
  await expect.poll(state.events.active).toBe(0)
  const count = state.getCount()
  await page.waitForTimeout(1300)
  expect(state.getCount()).toBe(count)
  expect(
    await page.evaluate(() =>
      localStorage.getItem('jobscout.session_id.synthetic-browser-account'),
    ),
  ).toBeNull()
})

test('workflow failure uses backend retry without creating a second session', async ({ page }) => {
  const state = await mockSessions(
    page,
    createSessionFixture({
      outcome: 'failed',
      current_stage: 'failed',
      retryable: true,
      errors: [
        {
          code: 'analysis_unavailable',
          message: 'Model temporarily unavailable',
          action: 'retry',
        },
      ],
    }),
  )
  await introduce(page)
  await page
    .getByRole('region', { name: 'Search progress', exact: true })
    .getByRole('button', { name: 'Try again', exact: true })
    .click()
  await expect(
    page.getByRole('heading', { name: 'Review your profile and search criteria' }),
  ).toBeVisible()
  expect(state.requests[0]?.action).toBe('retry')
  expect(state.createCount()).toBe(1)
})

test('resume-only input is valid; required text control accepts free text', async ({ page }) => {
  const state = await mockSessions(
    page,
    createSessionFixture({
      current_stage: 'clarify',
      search_summary: null,
      clarification_questions: [makeQuestion('text', 'text')],
    }),
  )
  await page.goto('/new')
  await page.getByRole('button', { name: 'Analyze and continue' }).click()
  await expect(page.getByText('Add an introduction or upload a resume.')).toBeVisible()
  await page.locator('input[type=file]').setInputFiles({
    name: 'synthetic.txt',
    mimeType: 'text/plain',
    buffer: Buffer.from('Synthetic React project, no real personal data.'),
  })
  await page.getByRole('button', { name: 'Analyze and continue' }).click()
  await page.getByLabel('text question', { exact: true }).fill('香港')
  await page.getByRole('button', { name: 'Send and continue' }).click()
  await expect(page.getByRole('button', { name: 'Confirm and search' })).toBeEnabled()
  expect(state.createBodies[0]?.description).toBe('')
  expect(state.requests[0]?.answers).toEqual([{ question_id: 'text', value: '香港' }])
})

test('resume network retry preserves the complete typed request and visible correction', async ({
  page,
}) => {
  const state = await mockSessions(
    page,
    createSessionFixture({
      current_stage: 'clarify',
      search_summary: null,
      clarification_questions: [makeQuestion('text', 'text')],
    }),
  )
  await introduce(page)
  state.dropNextAnswer()
  await page
    .getByLabel('Add a note or correction', { exact: true })
    .fill('Only use the additional text to update the criteria.')
  await page.getByRole('button', { name: 'Send and continue' }).click()
  await expect(page.getByLabel('Add a note or correction', { exact: true })).toHaveValue(
    'Only use the additional text to update the criteria.',
  )
  await page.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Confirm and search' })).toBeEnabled()
  expect(state.requests).toHaveLength(2)
  expect(state.requests[1]).toEqual(state.requests[0])
  expect(state.requests[0]?.answers).toEqual([])
})

test('incomplete summary requires updates; explicit unrestricted flags use flat fields', async ({
  page,
}) => {
  const fixture = createSessionFixture()
  const state = await mockSessions(page, {
    ...fixture,
    search_summary: {
      ...fixture.search_summary!,
      ready: false,
      missing_fields: ['preferences.location'],
    },
  })
  await introduce(page)
  await expect(page.getByRole('button', { name: 'Confirm and search' })).toBeDisabled()
  await page.getByRole('checkbox', { name: 'Any location', exact: true }).check()
  await page.getByRole('button', { name: 'Update criteria' }).click()
  await expect(page.getByRole('button', { name: 'Confirm and search' })).toBeEnabled()
  expect(state.requests[0]?.profile_updates).toEqual({
    'preferences.location_unrestricted': true,
    'preferences.location': null,
  })
  expect(state.requests[0]?.action).toBe('edit_conditions')
})

test('stale summary cannot be confirmed even when marked ready', async ({ page }) => {
  const fixture = createSessionFixture({ revision: 2 })
  const state = await mockSessions(page, fixture)
  await introduce(page)
  await expect(page.getByRole('button', { name: 'Confirm and search' })).toBeDisabled()
  await page.getByRole('button', { name: 'Reload search', exact: true }).click()
  await expect.poll(state.getCount).toBe(1)
  await expect(page.getByRole('button', { name: 'Confirm and search' })).toBeDisabled()
  expect(state.requests).toEqual([])
})

test('a missing search route offers a fresh start without browser-stored private material', async ({
  page,
}) => {
  await mockSessions(page)
  await page.goto('/searches/expired')
  await page.getByRole('main').getByRole('link', { name: 'New search', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Analyze and continue' })).toBeEnabled()
  expect(
    await page.evaluate(() =>
      localStorage.getItem('jobscout.session_id.synthetic-browser-account'),
    ),
  ).toBeNull()
})

test('conversation preserves supplied free text and structured answers', async ({ page }) => {
  const fixture = createSessionFixture({
    current_stage: 'clarify',
    search_summary: null,
    clarification_questions: [
      { ...makeQuestion('location', 'text'), question: 'Where would you like to work?' },
    ],
    conversation: [
      {
        message_id: 'assistant-1',
        role: 'assistant',
        text: 'What kind of roles are you looking for?',
        responses: [],
        question_ids: [],
        created_at: '2026-10-03T00:00:00Z',
      },
      {
        message_id: 'free-text-user',
        role: 'user',
        text: "测试\ntarget_directions: ['技术/研发', '产品/项目']\npreferences.location: 不限\npreferences.employment_type: full-time",
        responses: [],
        question_ids: [],
        created_at: '2026-10-03T00:00:00Z',
      },
      {
        message_id: 'structured-user',
        role: 'user',
        text: '我希望有导师指导。',
        question_ids: [],
        created_at: '2026-10-03T00:00:00Z',
        responses: [
          {
            label: 'Job interests',
            value: ['Frontend development', 'Data analysis'],
            status: 'answered',
          },
          { label: 'Work location', value: 'Hong Kong', status: 'answered' },
          { label: 'Industry', value: '', status: 'skipped' },
        ],
      },
    ],
  })
  await mockSessions(page, fixture)
  await introduce(page)
  const history = page.getByRole('log', { name: 'Conversation history' })
  await expect(history).toBeHidden()
  await page.getByText('View conversation history', { exact: true }).press('Enter')
  await expect(history).toBeVisible()
  await expect(history).toContainText(fixture.conversation[1]!.text)
  await expect(history).toContainText(fixture.conversation[2]!.text)
  await expect(history).toContainText('Frontend development')
  await expect(history).toContainText('Data analysis')
  await expect(history).toContainText('Hong Kong')
  if (process.env.JOBSCOUT_REVIEW_SCREENSHOTS === '1') {
    await mkdir('.tools/review', { recursive: true })
    await page.setViewportSize({ width: 1440, height: 1100 })
    await page.evaluate(() => window.scrollTo(0, 0))
    await page.screenshot({
      path: '.tools/review/conversation-desktop.png',
      fullPage: true,
      animations: 'disabled',
    })
    await page.setViewportSize({ width: 390, height: 900 })
    await page.evaluate(() => window.scrollTo(0, 0))
    await page.screenshot({
      path: '.tools/review/conversation-mobile.png',
      fullPage: true,
      animations: 'disabled',
    })
  }
  await page.setViewportSize({ width: 390, height: 900 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  )
})

test('clarification drafts preserve choices, skips and text across workspace navigation', async ({
  page,
}) => {
  const state = await mockSessions(
    page,
    createSessionFixture({
      current_stage: 'clarify',
      search_summary: null,
      clarification_questions: [
        makeQuestion('single', 'single_choice'),
        makeQuestion('multiple', 'multiple_choice'),
        makeQuestion('optional', 'text', false),
      ],
    }),
  )
  await introduce(page)
  await page.getByRole('radio', { name: 'Option one' }).check()
  await page.getByRole('checkbox', { name: 'Option two', exact: true }).check()
  await page.getByRole('checkbox', { name: 'Skip this question' }).check()
  await page
    .getByLabel('Add a note or correction', { exact: true })
    .fill('Shenzhen works for me too.')
  await page.getByRole('link', { name: 'Saved jobs', exact: false }).first().click()
  await expect(page).toHaveURL(/\/saved$/)
  await returnToSearch(page)
  await page.reload()
  await expect(page.getByRole('radio', { name: 'Option one' })).toBeChecked()
  await expect(page.getByRole('checkbox', { name: 'Option two', exact: true })).toBeChecked()
  await expect(page.getByRole('checkbox', { name: 'Skip this question' })).toBeChecked()
  await expect(page.getByLabel('Add a note or correction', { exact: true })).toHaveValue(
    'Shenzhen works for me too.',
  )
  await page.getByRole('button', { name: 'Send and continue' }).click()
  await expect(page.getByRole('button', { name: 'Confirm and search' })).toBeEnabled()
  expect(state.requests[0]).toMatchObject({
    answers: [
      { question_id: 'single', value: 'one-id' },
      { question_id: 'multiple', value: ['two-id'] },
    ],
    skipped_question_ids: ['optional'],
    message: 'Shenzhen works for me too.',
  })
})

test('direction choices allow more than three selections without dropping user choices', async ({
  page,
}) => {
  const question = {
    ...makeQuestion('directions', 'multiple_choice'),
    question: 'What kind of roles are you looking for?',
    field: 'target_directions',
    options: [
      'Frontend development',
      'Data analysis',
      'Product design',
      'Software engineering',
    ].map((label, index) => ({
      id: `direction-${index}`,
      label,
    })),
  }
  const state = await mockSessions(
    page,
    createSessionFixture({
      current_stage: 'clarify',
      search_summary: null,
      clarification_questions: [question],
    }),
  )
  await introduce(page)
  for (const label of ['Frontend development', 'Data analysis', 'Product design'])
    await page.getByRole('checkbox', { name: label, exact: true }).check()
  await expect(
    page.getByRole('checkbox', { name: 'Software engineering', exact: true }),
  ).toBeEnabled()
  await page.getByRole('checkbox', { name: 'Software engineering', exact: true }).focus()
  await page.keyboard.press('Space')
  await expect(
    page.getByRole('checkbox', { name: 'Software engineering', exact: true }),
  ).toBeChecked()
  if (process.env.JOBSCOUT_REVIEW_SCREENSHOTS === '1') {
    await mkdir('.tools/review', { recursive: true })
    await page.setViewportSize({ width: 1440, height: 1100 })
    await page.evaluate(() => window.scrollTo(0, 0))
    await page.screenshot({
      path: '.tools/review/clarification-desktop.png',
      fullPage: true,
      animations: 'disabled',
    })
    await page.setViewportSize({ width: 390, height: 900 })
    await page.evaluate(() => window.scrollTo(0, 0))
    await page.screenshot({
      path: '.tools/review/clarification-mobile.png',
      fullPage: true,
      animations: 'disabled',
    })
  }
  await page.getByRole('checkbox', { name: 'Product design', exact: true }).uncheck()
  await expect(
    page.getByRole('checkbox', { name: 'Software engineering', exact: true }),
  ).toBeChecked()
  await page.getByRole('checkbox', { name: 'Product design', exact: true }).check()
  expect(state.requests).toEqual([])
  await page.getByRole('button', { name: 'Send and continue' }).click()
  await expect(page.getByRole('button', { name: 'Confirm and search' })).toBeEnabled()
  expect(state.requests[0]?.answers).toEqual([
    {
      question_id: 'directions',
      value: ['direction-0', 'direction-1', 'direction-3', 'direction-2'],
    },
  ])
})

test('summary edits preserve all directions across navigation and submission, and new revision clears message', async ({
  page,
}) => {
  const state = await mockSessions(page)
  await introduce(page)
  await page.getByRole('button', { name: 'Edit search conditions', exact: true }).click()
  const directions = page.getByLabel('Job interests', { exact: true })
  await directions.fill('Frontend development\nData analysis\nProduct design\nSoftware engineering')
  await expect(page.getByRole('button', { name: 'Update criteria' })).toBeEnabled()
  await expect(directions).toHaveValue(
    'Frontend development\nData analysis\nProduct design\nSoftware engineering',
  )
  await page.getByRole('button', { name: 'Edit experience', exact: true }).click()
  await page.getByLabel('Skills', { exact: true }).fill('React\nSQL')
  await page
    .getByLabel('Add or correct search criteria', { exact: true })
    .fill('I’d like mentorship.')
  await page.getByRole('link', { name: 'Saved jobs', exact: false }).first().click()
  await expect(page).toHaveURL(/\/saved$/)
  await returnToSearch(page)
  await page.reload()
  await expect(directions).toHaveValue(
    'Frontend development\nData analysis\nProduct design\nSoftware engineering',
  )
  await expect(page.getByLabel('Skills', { exact: true })).toHaveValue('React\nSQL')
  await expect(page.getByLabel('Add or correct search criteria', { exact: true })).toHaveValue(
    'I’d like mentorship.',
  )
  await page.getByRole('button', { name: 'Update criteria' }).click()
  await expect(page.getByRole('button', { name: 'Confirm and search' })).toBeEnabled()
  await expect(page.getByLabel('Add or correct search criteria', { exact: true })).toHaveValue('')
  await page.getByRole('button', { name: 'Edit search conditions', exact: true }).click()
  expect(state.requests[0]?.profile_updates).toEqual({
    skills: ['React', 'SQL'],
    target_directions: [
      'Frontend development',
      'Data analysis',
      'Product design',
      'Software engineering',
    ],
  })
  await expect(directions).toHaveValue(
    'Frontend development\nData analysis\nProduct design\nSoftware engineering',
  )
  expect(await page.evaluate(() => Object.keys(sessionStorage))).toEqual([])
})

function resultSession() {
  const first = createRecommendationFixture()
  first.job.salary = 'HK$25,000–32,000 / month'
  first.job.responsibilities = [
    'Build responsive React interfaces and connect them to backend services.',
  ]
  first.job.freshness_status = 'active'
  first.analysis_status = 'complete'
  const second = structuredClone(first)
  second.job.job_id = 'test-job-2'
  second.job.title = 'Full Stack Engineer'
  second.job.target_direction = 'Full stack development'
  second.job.target_directions = ['Full stack development']
  second.job.freshness_status = 'unknown'
  const third = structuredClone(second)
  third.job.job_id = 'test-job-3'
  third.job.title = 'Frontend Developer'
  third.job.target_direction = 'Frontend development'
  third.job.target_directions = ['Frontend development']
  return createSessionFixture({
    outcome: 'completed',
    current_stage: 'completed',
    recommendation: {
      session_id: 'session-1',
      generated_at: '2026-10-06T00:00:00Z',
      introduction: '',
      notices: [],
      jobs: [first, second, third],
      pending_jobs: [],
    },
  })
}

async function captureResults(page: Page, name: string) {
  if (process.env.JOBSCOUT_REVIEW_SCREENSHOTS !== '1') return
  await mkdir('.tools/review', { recursive: true })
  await page.evaluate(() => window.scrollTo(0, 0))
  await page.evaluate(() =>
    Promise.all(document.getAnimations().map((animation) => animation.finished.catch(() => {}))),
  )
  await page.screenshot({
    path: `.tools/review/${name}.png`,
    fullPage: true,
    animations: 'disabled',
  })
}

test('result panes scroll independently and restore reading positions by job identity', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  const session = resultSession()
  const original = session.recommendation!.jobs[0]!
  session.profile!.search_options.result_count = 20
  session.recommendation!.jobs = Array.from({ length: 12 }, (_, index) => {
    const item = structuredClone(original)
    item.job.job_id = `long-list-${index}`
    item.job.title = `Engineer ${index + 1}`
    item.job.responsibilities = Array.from(
      { length: 30 },
      (_, task) => `Engineer ${index + 1}: supplied responsibility ${task + 1}.`,
    )
    return item
  })
  await mockSessions(page, session)
  await introduce(page)
  const detail = page.getByRole('article', { name: 'Job details', exact: true })
  const analysis = detail.getByRole('region', { name: 'Job analysis', exact: true })
  const list = page.getByRole('region', { name: 'Job list', exact: true })
  const later = page.getByRole('button', { name: 'View job: Engineer 9', exact: true })
  await later.scrollIntoViewIfNeeded()
  await expect(detail.getByRole('heading', { name: 'Engineer 1', exact: true })).toBeInViewport()
  const pageScroll = await page.evaluate(() => window.scrollY)
  expect(pageScroll).toBe(0)
  expect(
    await page.evaluate(() => document.documentElement.scrollHeight <= window.innerHeight),
  ).toBe(true)
  const listPosition = await list.evaluate((element) => element.scrollTop)
  expect(listPosition).toBeGreaterThan(0)
  const listing = detail.getByRole('link', { name: 'View job listing', exact: true })
  await analysis.focus()
  await page.keyboard.press('PageDown')
  await expect.poll(() => analysis.evaluate((element) => element.scrollTop)).toBeGreaterThan(0)
  expect(await page.evaluate(() => window.scrollY)).toBe(pageScroll)
  expect(await list.evaluate((element) => element.scrollTop)).toBe(listPosition)
  await later.click()
  await expect(page).toHaveURL(/job=long-list-8/)
  await expect(detail.getByRole('heading', { name: 'Engineer 9', exact: true })).toBeInViewport()
  expect(await analysis.evaluate((element) => element.scrollTop)).toBe(0)
  expect(await list.evaluate((element) => element.scrollTop)).toBe(listPosition)
  const lastResponsibility = detail.getByText('Engineer 9: supplied responsibility 30.', {
    exact: true,
  })
  await lastResponsibility.scrollIntoViewIfNeeded()
  await expect(lastResponsibility).toBeInViewport()
  await expect(listing).toBeInViewport()
  await expect(detail.getByRole('heading', { name: 'Engineer 9', exact: true })).toBeInViewport()
  await expect(page.getByRole('combobox', { name: 'Sort jobs' })).toBeInViewport()
  const readingPosition = await analysis.evaluate((element) => element.scrollTop)
  await page.getByRole('button', { name: 'View job: Engineer 10', exact: true }).click()
  await expect(analysis).toHaveJSProperty('scrollTop', 0)
  await later.click()
  await expect(analysis).toHaveJSProperty('scrollTop', readingPosition)
  await detail.getByRole('button', { name: 'Save job: Engineer 9', exact: true }).click()
  await expect(
    detail.getByRole('button', { name: 'Remove saved job: Engineer 9', exact: true }),
  ).toBeVisible()
  await expect(analysis).toHaveJSProperty('scrollTop', readingPosition)
  await analysis.evaluate((element) => {
    element.scrollTop = element.scrollHeight
  })
  await analysis.hover()
  await page.mouse.wheel(0, 800)
  expect(await page.evaluate(() => window.scrollY)).toBe(0)
  if (process.env.JOBSCOUT_REVIEW_SCREENSHOTS === '1') {
    await mkdir('.tools/review', { recursive: true })
    await page.screenshot({ path: '.tools/review/results-sticky-desktop.png' })
  }
  await page.setViewportSize({ width: 1440, height: 500 })
  await lastResponsibility.scrollIntoViewIfNeeded()
  await expect(lastResponsibility).toBeInViewport()
  await expect(listing).toBeInViewport()
})

test('search criteria expands in the page and leaves results reachable on short screens', async ({
  page,
}) => {
  await mockSessions(page, resultSession())
  await introduce(page)
  const criteria = page.getByRole('region', { name: 'Search criteria', exact: true })
  const results = page.getByRole('region', { name: 'Recommended jobs', exact: true })
  for (const height of [900, 500]) {
    await page.setViewportSize({ width: 1440, height })
    await page.emulateMedia({ reducedMotion: 'no-preference' })
    const closedHeight = await criteria.evaluate(
      (element) => element.getBoundingClientRect().height,
    )
    await criteria.locator('summary').click()
    await criteria.evaluate(async (element) => {
      await Promise.all(
        element.getAnimations({ subtree: true }).map((animation) => animation.finished),
      )
    })
    const expanded = await criteria.boundingBox()
    const resultsBounds = await results.boundingBox()
    expect(expanded!.height).toBeGreaterThan(closedHeight)
    expect(resultsBounds!.y).toBeGreaterThanOrEqual(expanded!.y + expanded!.height)
    const listing = page.getByRole('link', { name: 'View job listing', exact: true })
    await listing.scrollIntoViewIfNeeded()
    await expect(listing).toBeInViewport()
    await criteria.locator('summary').click()
    await expect(criteria.locator('details')).not.toHaveAttribute('open')
    await expect
      .poll(() => criteria.evaluate((element) => element.getBoundingClientRect().height))
      .toBe(closedHeight)
    await expect(
      page.getByRole('button', { name: 'View job: React Engineer', exact: true }),
    ).toBeInViewport()
  }
})

test('search failure preserves published job identities until editing the criteria', async ({
  page,
}) => {
  const failed = resultSession()
  failed.outcome = 'failed'
  failed.current_stage = 'failed'
  failed.retryable = true
  failed.run_id = 'failed-run'
  failed.errors = [
    { code: 'search_interrupted', message: 'private-failure-detail', action: 'retry' },
  ]
  const state = await mockSessions(page, failed)
  state.seedSession(failed)
  await page.goto('/searches/session-1')
  await expect(
    page
      .getByRole('region', { name: 'Search progress', exact: true })
      .getByRole('button', { name: 'Try again', exact: true }),
  ).toBeVisible()
  for (const item of failed.recommendation!.jobs)
    await expect(
      page.getByRole('button', { name: `View job: ${item.job.title}`, exact: true }),
    ).toBeVisible()
  await expect(page.locator('body')).not.toContainText('private-failure-detail')
  await page.getByRole('button', { name: 'Edit search criteria', exact: true }).first().click()
  await page.getByRole('button', { name: 'Edit search conditions', exact: true }).click()
  await expect(page.getByLabel('Job interests', { exact: true })).toBeVisible()
  await expect(page.getByRole('article', { name: 'Job details', exact: true })).toHaveCount(0)
  expect(state.requests.at(-1)?.action).toBe('edit_conditions')
})

test('result selection and filters retain job identity and saved removal chooses a neighbor', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1100 })
  await mockSessions(page, resultSession())
  await introduce(page)
  const detail = page.getByRole('article', { name: 'Job details', exact: true })
  await expect(detail.getByRole('heading', { name: 'React Engineer', exact: true })).toBeVisible()
  await detail.getByRole('button', { name: 'Save job: React Engineer', exact: true }).click()
  await page.getByRole('button', { name: 'View job: Full Stack Engineer', exact: true }).click()
  await expect(page).toHaveURL(/job=test-job-2/)
  await detail.getByRole('button', { name: 'Save job: Full Stack Engineer', exact: true }).click()
  await page.getByRole('button', { name: 'Frontend development', exact: true }).click()
  await expect(
    page.getByRole('button', { name: 'View job: Full Stack Engineer', exact: true }),
  ).toHaveCount(0)
  await expect(
    detail.getByRole('heading', { name: 'Frontend Developer', exact: true }),
  ).toBeVisible()
  await page.getByRole('button', { name: 'Filters', exact: true }).click()
  await page.getByRole('combobox', { name: 'Filter by listing status' }).selectOption('expired')
  await page.getByRole('button', { name: 'Close filters', exact: true }).click()
  await expect(page.getByRole('article', { name: 'Job details', exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: 'Clear filters', exact: true }).click()
  await captureResults(page, 'results-desktop')
  await page.getByRole('link', { name: 'Saved jobs', exact: false }).first().click()
  await detail
    .getByRole('button', { name: 'Remove saved job: React Engineer', exact: true })
    .click()
  await expect(
    detail.getByRole('heading', { name: 'Full Stack Engineer', exact: true }),
  ).toBeVisible()
  await expect(
    page.getByRole('button', { name: 'View job: React Engineer', exact: true }),
  ).toHaveCount(0)
  await detail
    .getByRole('button', { name: 'Remove saved job: Full Stack Engineer', exact: true })
    .click()
  await expect(page.getByRole('article', { name: 'Job details', exact: true })).toHaveCount(0)
  await returnToSearch(page)
  await expect(
    page.getByRole('button', { name: 'View job: React Engineer', exact: true }),
  ).toBeVisible()
})

test('combined result filters and sorting survive reload and retain selected job identity', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1000 })
  const session = resultSession()
  const [first, second, third] = session.recommendation!.jobs
  first!.job.posted_at = '2026-10-03T00:00:00Z'
  first!.match_score = { ...createMatchScoreFixture(), total: 0 }
  second!.match_score = { ...createMatchScoreFixture(), total: 95 }
  second!.recommendation_fit = 'possible'
  second!.job.employment_type = 'part-time'
  third!.job.posted_at = '2026-10-07T00:00:00Z'
  const state = await mockSessions(page, session)
  state.seedSession(session)
  await page.goto('/searches/session-1')
  const list = page.getByRole('region', { name: 'Job list', exact: true })
  const jobTitles = () => list.getByRole('button').allTextContents()
  const detail = page.getByRole('article', { name: 'Job details', exact: true })
  await page.getByRole('button', { name: 'View job: Frontend Developer', exact: true }).click()
  await page.getByRole('combobox', { name: 'Sort jobs' }).selectOption('match')
  await expect
    .poll(jobTitles)
    .toEqual([
      expect.stringContaining('Full Stack Engineer'),
      expect.stringContaining('React Engineer'),
      expect.stringContaining('Frontend Developer'),
    ])
  await expect(page).toHaveURL(/job=test-job-3/)
  await expect(
    detail.getByRole('heading', { name: 'Frontend Developer', exact: true }),
  ).toBeVisible()
  await page.getByRole('combobox', { name: 'Sort jobs' }).selectOption('newest')
  await expect
    .poll(jobTitles)
    .toEqual([
      expect.stringContaining('Frontend Developer'),
      expect.stringContaining('React Engineer'),
      expect.stringContaining('Full Stack Engineer'),
    ])
  await captureResults(page, 'result-filters-desktop')
  await page.getByRole('button', { name: 'Filters', exact: true }).click()
  await page.getByRole('combobox', { name: 'Filter by listing status' }).selectOption('unknown')
  await page.getByRole('combobox', { name: 'Filter by match result' }).selectOption('possible')
  await page.getByRole('combobox', { name: 'Filter by employment type' }).selectOption('part-time')
  await captureResults(page, 'result-filters-panel-desktop')
  await page.keyboard.press('Escape')
  if (process.env.JOBSCOUT_REVIEW_SCREENSHOTS === '1')
    await page.getByRole('group', { name: 'Job filters and sorting', exact: true }).screenshot({
      path: '.tools/review/result-filters-bar-desktop.png',
      animations: 'disabled',
    })
  await expect.poll(jobTitles).toEqual([expect.stringContaining('Full Stack Engineer')])
  await expect(page).toHaveURL(/job=test-job-2/)
  await page.reload()
  await expect(page.getByRole('combobox', { name: 'Sort jobs' })).toHaveValue('newest')
  await expect.poll(jobTitles).toEqual([expect.stringContaining('Full Stack Engineer')])
  await page.getByRole('button', { name: /^Filters/ }).click()
  await page.getByRole('combobox', { name: 'Filter by match result' }).selectOption('')
  await expect(page).not.toHaveURL(/fit=/)
  await page.getByRole('combobox', { name: 'Filter by listing status' }).selectOption('expired')
  await page.getByRole('button', { name: 'Close filters', exact: true }).click()
  await expect(list).toHaveCount(0)
  await page.getByRole('button', { name: 'Clear filters', exact: true }).click()
  await expect
    .poll(jobTitles)
    .toEqual([
      expect.stringContaining('Frontend Developer'),
      expect.stringContaining('React Engineer'),
      expect.stringContaining('Full Stack Engineer'),
    ])
  await expect(page.getByRole('combobox', { name: 'Sort jobs' })).toHaveValue('newest')
})

test('mobile filters dismiss with Escape, preserve sort when cleared and fit within the viewport', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 900 })
  const session = resultSession()
  const state = await mockSessions(page, session)
  state.seedSession(session)
  await page.goto('/searches/session-1')
  const filters = page.getByRole('button', { name: 'Filters', exact: true })
  await filters.click()
  const status = page.getByRole('combobox', { name: 'Filter by listing status' })
  await status.selectOption('active')
  await captureResults(page, 'result-filters-panel-mobile')
  await status.focus()
  await page.keyboard.press('Escape')
  await expect(status).not.toBeVisible()
  await expect(page.getByRole('button', { name: 'Filters 1', exact: true })).toBeFocused()
  const list = page.getByRole('region', { name: 'Job list', exact: true })
  await expect(list.getByRole('button')).toHaveAttribute('aria-label', 'View job: React Engineer')
  await page.getByRole('combobox', { name: 'Sort jobs' }).selectOption('company')
  await page.getByRole('button', { name: 'Clear filters', exact: true }).click()
  await expect(page.getByRole('combobox', { name: 'Sort jobs' })).toHaveValue('company')
  await expect(list.getByRole('button')).toHaveCount(3)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  )
  await captureResults(page, 'result-filters-mobile')
  await filters.click()
  await page.getByRole('button', { name: 'All jobs', exact: true }).click()
  await expect(status).not.toBeVisible()
  await page.getByRole('button', { name: 'Full stack development', exact: true }).click()
  await expect(list.getByRole('button')).toHaveAttribute(
    'aria-label',
    'View job: Full Stack Engineer',
  )
  await expect(page.getByRole('button', { name: 'Clear filters', exact: true })).toBeInViewport()
  await expect(page.getByRole('combobox', { name: 'Sort jobs' })).toBeInViewport()
  await page.getByRole('button', { name: 'Clear filters', exact: true }).click()
  await expect(list.getByRole('button')).toHaveCount(3)
})

test('mobile detail Back and browser Back restore the selected list control without overflow', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 900 })
  await mockSessions(page, resultSession())
  await introduce(page)
  const row = page.getByRole('button', { name: 'View job: Full Stack Engineer', exact: true })
  await row.scrollIntoViewIfNeeded()
  await captureResults(page, 'results-mobile-list')
  await row.click()
  await expect(page.getByRole('article', { name: 'Job details', exact: true })).toBeVisible()
  await expect(
    page.getByRole('heading', { name: 'Full Stack Engineer', exact: true }),
  ).toBeFocused()
  await captureResults(page, 'results-mobile-detail')
  await page.goBack()
  await expect(row).toBeVisible()
  await expect(row).toBeFocused()
  await row.click()
  await page.getByRole('button', { name: 'Back to jobs', exact: true }).click()
  await expect(row).toBeFocused()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  )
})

test('job notices and source coverage retain actionable details when analysis is incomplete', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1100 })
  const session = resultSession()
  const item = session.recommendation!.jobs[0]!
  item.job.job_id = 'gen-private-id'
  item.matching_reasons[0]!.job_source_quotes[0]!.document_id = 'private-document-id'
  item.analysis_status = 'unavailable'
  item.preparation_suggestions = ['unsupported-preparation-sentinel']
  item.notices = [
    {
      code: 'analysis_unavailable',
      scope: 'job',
      job_id: item.job.job_id,
      source: null,
      preference: null,
      message:
        'Personal match analysis is unavailable for this role. You can still read the listing.',
      action: 'open_listing',
    },
  ]
  session.notices = [
    item.notices[0]!,
    {
      code: 'source_unavailable',
      scope: 'source',
      source: 'liepin',
      job_id: null,
      preference: null,
      message: 'Liepin was unavailable. These results are from the other sources searched.',
      action: null,
    },
  ]
  session.recommendation!.notices = session.notices
  session.notices.push({
    code: 'source_partial',
    scope: 'source',
    job_id: null,
    source: 'jobsdb',
    preference: null,
    action: null,
    message: 'Only some listings from JobsDB were available.',
  })
  item.job.description_is_excerpt = true
  item.notices.push({
    code: 'listing_incomplete',
    scope: 'job',
    job_id: item.job.job_id,
    source: null,
    preference: null,
    message: 'This listing is a summary. Check the full listing before applying.',
    action: 'open_listing',
  })
  item.matching_reasons[0]!.profile_source_quotes[0]!.excerpt = 'I worked on Group 6 using Python.'
  session.source_outcomes = [
    {
      request_index: 0,
      target_direction: 'Frontend development',
      source: 'liepin',
      candidate_count: 0,
      returned_count: 0,
      incomplete_count: 0,
      excerpt_count: 0,
      elapsed_seconds: 1,
      status: 'blocked',
    },
  ]
  await mockSessions(page, session)
  await introduce(page)
  const detail = page.getByRole('article', { name: 'Job details', exact: true })
  await expect(detail).toBeVisible()
  for (const summary of await detail.locator('details > summary').all()) await summary.click()
  await expect(detail.getByRole('link', { name: 'View job listing', exact: true })).toHaveAttribute(
    'href',
    item.job.source_url,
  )
  await expect(detail).toContainText(item.job.responsibilities[0]!)
  await expect(
    detail.getByText(`“${item.matching_reasons[0]!.profile_source_quotes[0]!.excerpt}”`, {
      exact: true,
    }),
  ).toBeVisible()
  await expect(detail).not.toContainText('unsupported-preparation-sentinel')
  await expect(detail.getByText(item.notices[0]!.message, { exact: true })).toHaveCount(1)
  await expect(
    page.getByRole('complementary', { name: 'Search coverage', exact: true }),
  ).toHaveCount(0)
  await expect(page.getByRole('alert')).toHaveCount(0)
  const visible = await page.locator('body').innerText()
  for (const internalId of [item.job.job_id, 'private-document-id'])
    expect(visible).not.toContain(internalId)
  await captureResults(page, 'results-expanded-notices')
  await page.getByRole('button', { name: 'Search details', exact: true }).click()
  const record = page.getByRole('dialog', { name: 'Search details', exact: true })
  await record.getByText('Job sites searched', { exact: true }).click()
  await expect(
    record.getByRole('listitem').filter({ hasText: 'Liepin · Frontend development' }),
  ).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(record).not.toBeVisible()
  await expect(page.getByRole('button', { name: 'Search details', exact: true })).toBeFocused()
})

test('empty completed search offers recovery without inventing jobs', async ({ page }) => {
  const empty = resultSession()
  empty.recommendation!.jobs = []
  empty.source_outcomes = [
    {
      request_index: 0,
      target_direction: 'Frontend development',
      source: 'liepin',
      candidate_count: 0,
      returned_count: 0,
      incomplete_count: 0,
      excerpt_count: 0,
      elapsed_seconds: 1,
      status: 'blocked',
    },
  ]
  const state = await mockSessions(page, empty)
  await introduce(page)
  await expect(page.getByRole('article', { name: 'Job details', exact: true })).toHaveCount(0)
  await page.getByText('Job sites searched', { exact: true }).click()
  await expect(
    page.getByRole('listitem').filter({ hasText: 'Liepin · Frontend development' }),
  ).toBeVisible()
  await captureResults(page, 'results-empty')
  await page.getByRole('button', { name: 'Edit search criteria', exact: true }).last().click()
  await expect(page.getByRole('button', { name: 'Confirm and search' })).toBeEnabled()
  expect(state.requests.at(-1)?.action).toBe('edit_conditions')
})

test('invalid selected deep links recover to the list and service failure allows a corrected search', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 900 })
  const loaded = await mockSessions(page, resultSession())
  loaded.seedSession(resultSession())
  await page.goto('/searches/session-1?job=discarded-record&freshness=not-a-status')
  await expect(
    page.getByRole('button', { name: 'View job: React Engineer', exact: true }),
  ).toBeVisible()
  await expect(page).not.toHaveURL(/discarded-record/)
  await expect(page.getByRole('article', { name: 'Job details', exact: true })).not.toBeVisible()
  const state = await mockSessions(
    page,
    createSessionFixture({
      outcome: 'failed',
      current_stage: 'failed',
      retryable: false,
      errors: [
        {
          code: 'service_unavailable',
          message: 'SOURCE_CONFIG_MISSING private-api-key',
          action: null,
        },
      ],
    }),
  )
  state.seedSession(
    createSessionFixture({
      outcome: 'failed',
      current_stage: 'failed',
      retryable: false,
      errors: [
        {
          code: 'service_unavailable',
          message: 'SOURCE_CONFIG_MISSING private-api-key',
          action: null,
        },
      ],
    }),
  )
  await page.reload()
  await expect(page.getByRole('button', { name: 'Try again', exact: true })).toHaveCount(0)
  await expect(page.locator('body')).not.toContainText('SOURCE_CONFIG_MISSING')
  await captureResults(page, 'search-service-failure')
  await page.getByRole('button', { name: 'Edit search criteria', exact: true }).last().click()
  await expect(page.getByRole('button', { name: 'Confirm and search' })).toBeEnabled()
  expect(state.requests.at(-1)?.action).toBe('edit_conditions')
})

test('deletion requires confirmation and a failed deletion preserves the search, saved jobs and workspace draft', async ({
  page,
}) => {
  await mockSessions(page, resultSession())
  const deletions: string[] = []
  await page.route('**/api/v1/sessions/*', async (route) => {
    if (route.request().method() !== 'DELETE') return route.fallback()
    deletions.push(route.request().url())
    if (deletions.length === 1)
      await route.fulfill({
        status: 500,
        json: {
          detail: {
            code: 'service_unavailable',
            message: 'private-deletion-diagnostic',
            action: 'retry',
          },
        },
      })
    else await route.fallback()
  })
  await page.goto('/new')
  const introduction = 'Original introduction: React 项目 experience.'
  await page.getByLabel('About you', { exact: true }).fill(introduction)
  await page.locator('input[type=file]').setInputFiles({
    name: 'original.txt',
    mimeType: 'text/plain',
    buffer: Buffer.from('Original resume contents'),
  })
  await page.getByRole('button', { name: 'Analyze and continue' }).click()
  await page.getByRole('button', { name: 'Save job: React Engineer', exact: true }).click()
  await openHistory(page)
  const trigger = page.getByRole('button', { name: /^Delete search:/ }).first()
  await trigger.click()
  const dialog = page.getByRole('dialog', { name: /^Delete/ })
  await dialog.getByRole('button', { name: 'Keep search', exact: true }).click()
  await expect(trigger).toBeFocused()
  expect(deletions).toEqual([])
  await trigger.click()
  await dialog.getByRole('button', { name: 'Delete search', exact: true }).click()
  await expect(page.getByRole('alert')).toBeVisible()
  await expect(dialog).not.toContainText('private-deletion-diagnostic')
  await dialog.getByRole('button', { name: 'Keep search', exact: true }).click()
  await expect(trigger).toBeFocused()
  await expect(
    page.getByRole('button', { name: 'Remove saved job: React Engineer', exact: true }),
  ).toBeVisible()
  expect(
    await page.evaluate(() =>
      localStorage.getItem('jobscout.session_id.synthetic-browser-account'),
    ),
  ).toBe('session-1')
  await trigger.click()
  await dialog.getByRole('button', { name: 'Delete search', exact: true }).click()
  await expect(page.getByLabel('About you', { exact: true })).toHaveValue(introduction)
  await expect(
    page.getByRole('button', { name: 'Remove resume: original.txt', exact: true }),
  ).toBeVisible()
  expect(deletions).toEqual([deletions[0], deletions[0]])
  expect(
    await page.evaluate(() =>
      localStorage.getItem('jobscout.session_id.synthetic-browser-account'),
    ),
  ).toBeNull()
  await page.getByRole('link', { name: 'Saved jobs', exact: false }).first().click()
  await expect(
    page.getByRole('button', { name: 'View job: React Engineer', exact: true }),
  ).toBeVisible()
})

test('resume upload failures preserve typed input, hide diagnostics and allow a successful retry', async ({
  page,
}) => {
  const state = await mockSessions(page)
  const statuses = [422, 500, 200]
  await page.route('**/api/v1/resumes/parse', async (route) => {
    const status = statuses.shift()!
    await route.fulfill({
      status,
      json:
        status === 200
          ? { name: 'resume.pdf', text: 'Parsed resume experience' }
          : {
              detail: {
                code: 'no_extractable_text',
                message: 'private-parser-path Traceback None',
                action: 'edit_conditions',
              },
            },
    })
  })
  await page.goto('/new')
  const introduction = 'Keep this introduction unchanged.'
  await page.getByLabel('About you', { exact: true }).fill(introduction)
  const upload = () =>
    page.locator('input[type=file]').setInputFiles({
      name: 'resume.pdf',
      mimeType: 'application/pdf',
      buffer: Buffer.from('Synthetic PDF input'),
    })
  for (const status of [422, 500]) {
    const failed = page.waitForResponse(
      (response) => response.url().endsWith('/resumes/parse') && response.status() === status,
    )
    await upload()
    await failed
    await expect(page.getByRole('alert')).toBeVisible()
    await expect(page.getByRole('alert')).not.toContainText('private-parser-path')
    await expect(page.getByLabel('About you', { exact: true })).toHaveValue(introduction)
    await expect(
      page.getByRole('button', { name: 'Analyze and continue', exact: true }),
    ).toBeEnabled()
  }
  await upload()
  await expect(
    page.getByRole('button', { name: 'Remove resume: resume.pdf', exact: true }),
  ).toBeVisible()
  await page.getByRole('button', { name: 'Analyze and continue', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Confirm and search', exact: true })).toBeEnabled()
  expect(state.createBodies[0]).toMatchObject({
    description: introduction,
    resume: { name: 'resume.pdf', text: 'Parsed resume experience' },
  })
})

test('a delayed mutation response cannot restore a search after confirmed deletion', async ({
  page,
}) => {
  await mockSessions(page)
  let release!: () => void
  let finished!: () => void
  const gate = new Promise<void>((resolve) => {
    release = resolve
  })
  const delivered = new Promise<void>((resolve) => {
    finished = resolve
  })
  let started = false
  await page.route('**/api/v1/sessions/*/resume', async (route) => {
    started = true
    await gate
    try {
      await route.fulfill({ status: 202, json: resultSession() })
    } catch {
      /* The request was deliberately aborted by deletion. */
    }
    finished()
  })
  await introduce(page)
  await page.getByRole('button', { name: 'Confirm and search', exact: true }).click()
  await expect.poll(() => started).toBe(true)
  await deleteSearch(page)
  await expect(
    page.getByRole('button', { name: 'Analyze and continue', exact: true }),
  ).toBeVisible()
  release()
  await delivered
  await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => resolve())))
  await expect(
    page.getByRole('button', { name: 'Analyze and continue', exact: true }),
  ).toBeVisible()
  await expect(
    page.getByRole('button', { name: 'View job: React Engineer', exact: true }),
  ).toHaveCount(0)
  expect(
    await page.evaluate(() =>
      localStorage.getItem('jobscout.session_id.synthetic-browser-account'),
    ),
  ).toBeNull()
})

test('desktop drawer remembers expansion and focuses the current search', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  const state = await mockSessions(page)
  state.seedSession(createSessionFixture())
  await page.goto('/searches/session-1')
  const sidebar = page.locator('#workspace-sidebar')
  await expect(sidebar).toHaveCSS('width', '72px')
  await page.getByRole('button', { name: 'Expand sidebar', exact: true }).click()
  await expect(sidebar).toHaveCSS('width', '288px')
  await expect(page.locator('[data-session-id="session-1"]')).toBeFocused()
  await page.reload()
  await expect(sidebar).toHaveCSS('width', '288px')
  await page.getByRole('button', { name: 'Collapse sidebar', exact: true }).click()
  await expect(sidebar).toHaveCSS('width', '72px')
  await page.reload()
  await expect(sidebar).toHaveCSS('width', '72px')
})

test('sidebar toggling keeps its controls and document scroll position stable', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await mockSessions(page)
  await page.goto('/new')
  await expect(page.getByLabel('About you', { exact: true })).toBeVisible()
  await page.evaluate(() => window.scrollTo(0, 240))
  const scrollY = await page.evaluate(() => window.scrollY)
  expect(scrollY).toBeGreaterThan(0)
  const sidebar = page.locator('#workspace-sidebar')
  const toggle = sidebar.getByRole('button', { name: /^(Expand|Collapse) sidebar$/ })

  for (let cycle = 0; cycle < 3; cycle += 1) {
    await toggle.click()
    await expect(toggle).toHaveAttribute('aria-expanded', 'true')
    await expect(sidebar).toHaveCSS('width', '288px')
    expect(await page.evaluate(() => window.scrollY)).toBe(scrollY)
    await sidebar.getByText('Collapse sidebar', { exact: true }).click()
    await expect(sidebar).toHaveCSS('width', '72px')
    expect(await page.evaluate(() => window.scrollY)).toBe(scrollY)
  }
})

test('mobile drawer isolates the page, traps focus and restores the trigger on Escape', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await mockSessions(page)
  await page.goto('/new')
  const trigger = page.getByRole('button', { name: 'Open sidebar', exact: true })
  await trigger.click()
  const sidebar = page.getByRole('dialog', { name: 'Workspace navigation', exact: true })
  await expect(sidebar).toBeVisible()
  await expect(page.locator('.drawer-content')).toHaveAttribute('inert', '')
  await sidebar.getByRole('button', { name: 'Close sidebar', exact: true }).last().focus()
  await page.keyboard.press('Tab')
  await expect(
    sidebar.getByRole('link', { name: 'JobScout — New search', exact: true }),
  ).toBeFocused()
  await page.keyboard.press('Shift+Tab')
  await expect(
    sidebar.getByRole('button', { name: 'Close sidebar', exact: true }).last(),
  ).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(sidebar).toHaveCount(0)
  await expect(trigger).toBeFocused()
  await expect(page.locator('.drawer-content')).not.toHaveAttribute('inert')
  await trigger.click()
  await sidebar.getByRole('link', { name: 'Saved jobs', exact: true }).click()
  await expect(page).toHaveURL(/\/saved$/)
  await expect(page.locator('.drawer-content')).not.toHaveAttribute('inert')
})

test('history loads twenty sessions per page and deleting another search preserves the current route', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  const state = await mockSessions(page)
  for (let index = 25; index >= 1; index -= 1)
    state.seedSession(createSessionFixture({ session_id: `history-${index}` }))
  await page.goto('/searches/history-1')
  await openHistory(page)
  await expect(page.locator('[data-session-id]')).toHaveCount(20)
  expect(state.historyRequests.at(-1)?.searchParams.get('limit')).toBe('20')
  await page.getByRole('button', { name: 'Load more', exact: true }).click()
  await expect(page.locator('[data-session-id="history-25"]')).toBeVisible()
  await expect(page.locator('[data-session-id]')).toHaveCount(25)
  expect(state.historyRequests.some((url) => url.searchParams.get('cursor') === '20')).toBe(true)
  await deleteSearch(page, 'history-2')
  await expect(page.locator('[data-session-id="history-2"]')).toHaveCount(0)
  await expect(page).toHaveURL(/\/searches\/history-1$/)
  expect(state.deleted).toEqual(['history-2'])
  await page.goto('/')
  await expect(page).toHaveURL(/\/searches\/history-1$/)
})

test('new search preserves history, saved snapshots and the profile draft across reload', async ({
  page,
}) => {
  const state = await mockSessions(page, resultSession())
  await introduce(page)
  await page.getByRole('button', { name: 'Save job: React Engineer', exact: true }).first().click()
  await page.getByRole('link', { name: 'New search', exact: true }).click()
  await expect(page).toHaveURL(/\/new$/)
  await expect(page.getByLabel('About you', { exact: true })).toHaveValue(
    'Synthetic test profile: React development experience.',
  )
  await page
    .getByLabel('About you', { exact: true })
    .fill('Draft preserved verbatim\n香港 React 项目')
  await expect
    .poll(() => state.readDraft('/workspace/draft')?.data.description)
    .toBe('Draft preserved verbatim\n香港 React 项目')
  await page.reload()
  await expect(page.getByLabel('About you', { exact: true })).toHaveValue(
    'Draft preserved verbatim\n香港 React 项目',
  )
  await returnToSearch(page)
  await expect(
    page.getByRole('button', { name: 'Remove saved job: React Engineer', exact: true }).first(),
  ).toBeVisible()
  await deleteSearch(page)
  await expect(page).toHaveURL(/\/new$/)
  await page.getByRole('link', { name: 'Saved jobs', exact: true }).click()
  await page.reload()
  await expect(
    page.getByRole('button', { name: 'View job: React Engineer', exact: true }),
  ).toBeVisible()
  expect(state.deleted).toEqual(['session-1'])
  expect(state.readDraft('/workspace/draft')?.data.description).toBe(
    'Draft preserved verbatim\n香港 React 项目',
  )
})

test('draft save failure and conflict retain raw input until an explicit recovery', async ({
  page,
}) => {
  const state = await mockSessions(page)
  await page.goto('/new')
  const input = page.getByLabel('About you', { exact: true })
  await expect(input).toBeEnabled()
  state.failNextDraft()
  await input.fill('Original whitespace  \n香港 skills')
  await expect(
    page.getByRole('alert').filter({ hasText: 'Could not save or load this draft' }),
  ).toBeVisible()
  await expect(input).toHaveValue('Original whitespace  \n香港 skills')
  await page.getByRole('button', { name: 'Try again', exact: true }).click()
  await expect
    .poll(() => state.readDraft('/workspace/draft')?.data.description)
    .toBe('Original whitespace  \n香港 skills')
  const previousRequest = state.draftRequests[0]!
  expect(state.draftRequests[1]?.request_id).toBe(previousRequest.request_id)
  state.changeDraft('/workspace/draft', {
    ...state.readDraft('/workspace/draft')!.data,
    description: 'Other workspace version',
  })
  await input.fill('My current version')
  await expect(page.getByRole('button', { name: 'Save my version', exact: true })).toBeVisible()
  await expect(input).toHaveValue('My current version')
  expect(state.readDraft('/workspace/draft')?.data.description).toBe('Other workspace version')
  await page.getByRole('button', { name: 'Save my version', exact: true }).click()
  await expect
    .poll(() => state.readDraft('/workspace/draft')?.data.description)
    .toBe('My current version')
  await page.reload()
  await expect(input).toHaveValue('My current version')
})

test('a delayed accepted response updates its original search without changing the new page', async ({
  page,
}) => {
  const state = await mockSessions(page)
  let release!: () => void
  const gate = new Promise<void>((resolve) => {
    release = resolve
  })
  let started = false
  await page.route('**/api/v1/sessions/*/resume', async (route) => {
    started = true
    await gate
    const result = resultSession()
    state.seedSession(result)
    await route.fulfill({ status: 202, json: result })
  })
  await introduce(page)
  await page.getByRole('button', { name: 'Confirm and search', exact: true }).click()
  await expect.poll(() => started).toBe(true)
  await page.getByRole('link', { name: 'New search', exact: true }).click()
  await expect(page).toHaveURL(/\/new$/)
  release()
  await expect(page.getByLabel('About you', { exact: true })).toBeVisible()
  await expect(page).toHaveURL(/\/new$/)
  await returnToSearch(page)
  await expect(
    page.getByRole('button', { name: 'View job: React Engineer', exact: true }),
  ).toBeVisible()
  expect(state.deleted).toEqual([])
})

test('autosave waits for IME composition to finish and preserves supplied text', async ({
  page,
}) => {
  const state = await mockSessions(page)
  await page.goto('/new')
  const input = page.getByLabel('About you', { exact: true })
  await expect(input).toBeEnabled()
  await input.dispatchEvent('compositionstart')
  await input.fill('香港 React 项目  \n原始换行')
  await page.waitForTimeout(650)
  expect(state.draftRequests).toEqual([])
  await input.dispatchEvent('compositionend')
  await expect
    .poll(() => state.readDraft('/workspace/draft')?.data.description)
    .toBe('香港 React 项目  \n原始换行')
  await page.reload()
  await expect(input).toHaveValue('香港 React 项目  \n原始换行')
})

test('an older current search remains available and receives focus after loading', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  const state = await mockSessions(page)
  for (let index = 25; index >= 1; index -= 1)
    state.seedSession(createSessionFixture({ session_id: `history-${index}` }))
  let release!: () => void
  const gate = new Promise<void>((resolve) => {
    release = resolve
  })
  await page.route('**/api/v1/sessions/history-25', async (route) => {
    await gate
    await route.fallback()
  })
  await page.goto('/searches/history-25')
  await openHistory(page)
  await expect(page.getByRole('heading', { name: 'Recent searches', exact: true })).toBeFocused()
  release()
  const active = page.locator('[data-session-id="history-25"]')
  await expect(active).toBeFocused()
  await expect(page.getByRole('heading', { name: 'Current search', exact: true })).toBeVisible()
  expect(state.historyRequests.every((url) => !url.searchParams.has('cursor'))).toBe(true)
  await page.getByRole('button', { name: 'Load more', exact: true }).click()
  await expect(active).toHaveCount(1)
  await expect(page.getByRole('heading', { name: 'Current search', exact: true })).toHaveCount(0)
})

test('a delayed create cannot navigate after leaving and returning to the new form', async ({
  page,
}) => {
  const state = await mockSessions(page)
  let release!: () => void
  let delivered!: () => void
  const gate = new Promise<void>((resolve) => {
    release = resolve
  })
  const completed = new Promise<void>((resolve) => {
    delivered = resolve
  })
  let started = false
  await page.route('**/api/v1/sessions', async (route) => {
    if (route.request().method() !== 'POST') {
      await route.fallback()
      return
    }
    started = true
    await gate
    const session = createSessionFixture()
    state.seedSession(session)
    await route.fulfill({ status: 202, json: session })
    delivered()
  })
  await introduce(page)
  await expect.poll(() => started).toBe(true)
  await page.getByRole('link', { name: 'Saved jobs', exact: true }).click()
  await expect(page).toHaveURL(/\/saved$/)
  await page.getByRole('link', { name: 'New search', exact: true }).click()
  await expect(page).toHaveURL(/\/new$/)
  const input = page.getByLabel('About you', { exact: true })
  await expect(input).toBeEnabled()
  await input.fill('New form information remains here.')
  release()
  await completed
  await openHistory(page)
  await expect(page.locator('[data-session-id="session-1"]')).toBeVisible()
  await expect(page).toHaveURL(/\/new$/)
  await expect(input).toHaveValue('New form information remains here.')
  await expect(input).toBeEnabled()
})

test('submitting a clarification locks input while its final draft save completes', async ({
  page,
}) => {
  const state = await mockSessions(
    page,
    createSessionFixture({
      current_stage: 'clarify',
      search_summary: null,
      clarification_questions: [makeQuestion('text', 'text')],
    }),
  )
  let release!: () => void
  const gate = new Promise<void>((resolve) => {
    release = resolve
  })
  let saving = false
  await page.route('**/api/v1/sessions/*/drafts/*/clarification', async (route) => {
    if (route.request().method() !== 'PUT') {
      await route.fallback()
      return
    }
    saving = true
    await gate
    await route.fallback()
  })
  await introduce(page)
  const input = page.getByLabel('text question', { exact: true })
  await input.fill('Hong Kong')
  await page.getByRole('button', { name: 'Send and continue', exact: true }).click()
  await expect.poll(() => saving).toBe(true)
  await expect(input).toBeDisabled()
  expect(state.requests).toEqual([])
  release()
  await expect(page.getByRole('button', { name: 'Confirm and search', exact: true })).toBeEnabled()
  expect(state.requests[0]?.answers).toEqual([{ question_id: 'text', value: 'Hong Kong' }])
})

test('a pending deletion cannot redirect away from a different search selected with browser history', async ({
  page,
}) => {
  const state = await mockSessions(page)
  state.seedSession(createSessionFixture({ session_id: 'session-2' }))
  await introduce(page)
  await returnToSearch(page, 'session-2')
  await expect(page).toHaveURL(/\/searches\/session-2$/)
  await page.goBack()
  await expect(page).toHaveURL(/\/searches\/session-1$/)
  let release!: () => void
  let delivered!: () => void
  const gate = new Promise<void>((resolve) => {
    release = resolve
  })
  const completed = new Promise<void>((resolve) => {
    delivered = resolve
  })
  let deleting = false
  await page.route('**/api/v1/sessions/session-1', async (route) => {
    if (route.request().method() !== 'DELETE') {
      await route.fallback()
      return
    }
    deleting = true
    await gate
    await route.fallback()
    delivered()
  })
  await deleteSearch(page)
  await expect.poll(() => deleting).toBe(true)
  await page.goForward()
  await expect(page).toHaveURL(/\/searches\/session-2$/)
  release()
  await completed
  await expect(page.locator('[data-session-id="session-1"]')).toHaveCount(0)
  await expect(page).toHaveURL(/\/searches\/session-2$/)
  expect(state.deleted).toEqual(['session-1'])
})

test('preferences preserve supplied values through reload and submission', async ({ page }) => {
  const state = await mockSessions(page)
  await page.goto('/new')
  await page
    .getByLabel('About you', { exact: true })
    .fill('React projects and internship experience')
  await page.getByLabel('Expected salary', { exact: false }).fill('HK$25,000 per month')
  await page.getByLabel('Work arrangement', { exact: false }).selectOption('remote')
  const slider = page.getByRole('slider', { name: 'Jobs to show', exact: true })
  await slider.press('End')
  for (let index = 0; index < 3; index++) await slider.press('ArrowLeft')
  await expect
    .poll(() => state.readDraft('/workspace/draft')?.data.search_options)
    .toEqual({ result_count: 17 })
  await page.reload()
  await expect(page.getByRole('slider', { name: 'Jobs to show', exact: true })).toBeVisible()
  await expect(page.getByLabel('Expected salary', { exact: false })).toHaveValue(
    'HK$25,000 per month',
  )
  await expect(page.getByLabel('Work arrangement', { exact: false })).toHaveValue('remote')
  await page.getByRole('button', { name: 'Analyze and continue' }).click()
  await expect(page.getByRole('button', { name: 'Confirm and search' })).toBeEnabled()
  expect(state.createBodies[0]).toMatchObject({
    search_options: { result_count: 17 },
    preferences: { salary_range: 'HK$25,000 per month', work_mode: 'remote' },
  })
})

test('a failed resume replacement retains the original file and introduction for submission', async ({
  page,
}) => {
  const state = await mockSessions(page)
  await page.route('**/api/v1/resumes/parse', (route) =>
    route.fulfill({ status: 503, json: { detail: { code: 'resume_parse_unavailable' } } }),
  )
  await page.goto('/new')
  const introduction = 'Additional project details supplied by the applicant'
  await page.getByLabel('About you', { exact: true }).fill(introduction)
  await page.locator('input[type="file"]').setInputFiles({
    name: 'original.txt',
    mimeType: 'text/plain',
    buffer: Buffer.from('Original resume experience'),
  })
  await expect(
    page.getByRole('button', { name: 'Remove resume: original.txt', exact: true }),
  ).toBeVisible()
  const chooserPromise = page.waitForEvent('filechooser')
  await page.getByRole('button', { name: 'Replace', exact: true }).click()
  const chooser = await chooserPromise
  await chooser.setFiles({
    name: 'replacement.pdf',
    mimeType: 'application/pdf',
    buffer: Buffer.from('%PDF replacement'),
  })
  await expect(page.getByRole('alert')).toBeVisible()
  await expect(
    page.getByRole('button', { name: 'Remove resume: original.txt', exact: true }),
  ).toBeVisible()
  await expect(page.getByLabel('About you', { exact: true })).toHaveValue(introduction)
  await page.getByRole('button', { name: 'Analyze and continue' }).click()
  await expect(page.getByRole('button', { name: 'Confirm and search' })).toBeEnabled()
  expect(state.createBodies[0]).toMatchObject({
    description: introduction,
    resume: { name: 'original.txt', text: 'Original resume experience' },
  })
})

test('match explanations support hover, keyboard dismissal and mobile activation', async ({
  page,
}) => {
  const session = resultSession()
  const score = createMatchScoreFixture()
  session.recommendation!.jobs[0]!.match_score = score
  const state = await mockSessions(page, session)
  state.seedSession(session)
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.goto('/searches/session-1')
  await page.getByRole('button', { name: 'View job: React Engineer', exact: true }).click()
  const details = page.getByRole('article', { name: 'Job details' })
  const skills = details.getByRole('button', { name: 'Skills: 80/100', exact: true })
  const tooltip = details.getByRole('tooltip').filter({ hasText: score.dimensions[0]!.explanation })
  await skills.hover()
  await expect(tooltip).toBeVisible()
  await tooltip.hover()
  await expect(tooltip).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(tooltip).toBeHidden()
  await skills.focus()
  await expect(tooltip).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(tooltip).toBeHidden()
  const responsibilities = details.getByRole('button', {
    name: 'Responsibilities: Not enough information',
    exact: true,
  })
  await responsibilities.focus()
  await expect(
    details.getByRole('tooltip').filter({
      hasText: score.dimensions[1]!.missing_information[0]!,
    }),
  ).toBeVisible()
  await page.keyboard.press('Escape')
  await page.setViewportSize({ width: 390, height: 900 })
  await skills.click()
  await expect(tooltip).toBeVisible()
  const bounds = await tooltip.boundingBox()
  expect(bounds!.x).toBeGreaterThanOrEqual(0)
  expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(390)
  await page.keyboard.press('Escape')
  await expect(tooltip).toBeHidden()
})

test('summary groups retain collapsed edits and require confirmation of the updated revision', async ({
  page,
}) => {
  const state = await mockSessions(page)
  await introduce(page)
  await expect(page.getByRole('button', { name: 'Confirm and search' })).toBeEnabled()
  await page.getByRole('button', { name: 'Edit experience', exact: true }).click()
  await page.getByLabel('Skills', { exact: true }).fill('React\nAccessible interfaces')
  await page.getByRole('button', { name: 'Close experience editor', exact: true }).click()
  await page.getByRole('button', { name: 'Edit other preferences', exact: true }).click()
  const slider = page.getByRole('slider', { name: 'Jobs to show', exact: true })
  await slider.press('End')
  for (let index = 0; index < 5; index++) await slider.press('ArrowLeft')
  await page.getByRole('button', { name: 'Close other preferences editor', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Confirm and search' })).toHaveCount(0)
  await page.getByRole('button', { name: 'Update criteria', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Confirm and search' })).toBeEnabled()
  expect(state.requests).toEqual([
    expect.objectContaining({
      action: 'edit_conditions',
      expected_revision: 1,
      profile_updates: { skills: ['React', 'Accessible interfaces'] },
      search_options: { result_count: 15 },
    }),
  ])
  await page.getByRole('button', { name: 'Confirm and search' }).click()
  await expect.poll(() => state.requests.at(-1)?.action).toBe('confirm_search')
  expect(state.requests.at(-1)?.expected_revision).toBe(2)
})

test.describe('job status tooltips', () => {
  test.use({ hasTouch: true })

  test('status reasons support touch, hover, keyboard and dismissal without selecting a job', async ({
    page,
  }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    const session = resultSession()
    const item = session.recommendation!.jobs[0]!
    item.analysis_status = 'unavailable'
    item.review_issue = { code: 'timeout', stage: 'matching' }
    const state = await mockSessions(page, session)
    state.seedSession(session)
    await page.goto('/searches/session-1')
    const card = page.locator('article').filter({
      has: page.getByRole('button', { name: `View job: ${item.job.title}`, exact: true }),
    })
    const badge = card.getByRole('button', { name: 'Timed out', exact: true })
    const tooltip = page.getByRole('tooltip')
    await badge.tap()
    await expect(tooltip).toBeVisible()
    await expect(badge).toHaveAttribute(
      'aria-describedby',
      (await tooltip.getAttribute('id')) as string,
    )
    await expect(page.getByRole('article', { name: 'Job details' })).not.toBeVisible()
    const bounds = await tooltip.boundingBox()
    expect(bounds).not.toBeNull()
    expect(bounds!.x).toBeGreaterThanOrEqual(0)
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(390)
    await mkdir('.tools/browser', { recursive: true })
    await page.screenshot({ path: '.tools/browser/status-tooltip-mobile.png', fullPage: true })
    await page.keyboard.press('Escape')
    await expect(tooltip).toHaveCount(0)
    await badge.blur()
    await badge.focus()
    await expect(tooltip).toBeVisible()
    await page.keyboard.press('Tab')
    await expect(tooltip).toHaveCount(0)
    await page.setViewportSize({ width: 1280, height: 900 })
    await page.mouse.move(5, 5)
    await badge.hover()
    await expect(tooltip).toBeVisible()
    await tooltip.hover()
    await expect(tooltip).toBeVisible()
    await page.screenshot({ path: '.tools/browser/status-tooltip-desktop.png', fullPage: true })
    await page.mouse.click(5, 5)
    await expect(tooltip).toHaveCount(0)
  })
})
