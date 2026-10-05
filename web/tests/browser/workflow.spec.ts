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
import { createRecommendationFixture, createSessionFixture } from '../fixtures'

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
  const getTimes: number[] = []
  const requests: ResumeSessionRequest[] = []
  const stopRequests: StopSessionRequest[] = []
  const createBodies: Record<string, unknown>[] = []
  let dropCreate = false
  let dropAnswer = false
  let conflict = false
  let failDraft = false
  let conflictDraft = false
  let runningPolls = 0
  let finish = snapshot
  function store(session: ScoutSession) {
    sessions.set(session.session_id, structuredClone(session))
    const index = order.indexOf(session.session_id)
    if (index >= 0) order.splice(index, 1)
    order.unshift(session.session_id)
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
    if (method === 'DELETE') {
      deleted.push(id!)
      sessions.delete(id!)
      const index = order.indexOf(id!)
      if (index >= 0) order.splice(index, 1)
      for (const key of drafts.keys()) if (key.startsWith(`/sessions/${id}/`)) drafts.delete(key)
      await route.fulfill({ status: 204 })
      return
    }
    if (method === 'GET') {
      getCount += 1
      getTimes.push(Date.now())
      if (!sessions.has(id!)) {
        await route.fulfill({
          status: 404,
          json: { detail: { code: 'search_not_found', action: 'start_new_search' } },
        })
        return
      }
      if (id === snapshot.session_id && runningPolls > 0 && --runningPolls === 0) {
        snapshot = structuredClone(finish)
        sessions.set(id, snapshot)
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
      runningPolls = 0
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
      finish = {
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
      runningPolls = 2
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
    getTimes,
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
    runFor: (polls: number, final: ScoutSession) => {
      snapshot = { ...snapshot, outcome: 'running', current_stage: 'extract' }
      if (sessions.has(snapshot.session_id)) sessions.set(snapshot.session_id, snapshot)
      runningPolls = polls
      finish = final
    },
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
  await page
    .getByRole('dialog', { name: 'Delete search?', exact: true })
    .getByRole('button', { name: 'Delete search', exact: true })
    .click()
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
    await page
      .getByLabel('Education', { exact: true })
      .fill('BSc, Computer Science\nHigher Diploma; with distinction')
    await page
      .getByLabel('Skills', { exact: true })
      .fill('CI/CD | deployment\nStatistics, research methods')
    await page.getByRole('button', { name: 'Save changes' }).click()
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
  const slider = page.getByRole('slider', { name: 'Matching jobs to find slider' })
  const number = page.getByRole('spinbutton', { name: 'Matching jobs to find', exact: true })
  await slider.focus()
  await page.keyboard.press('Home')
  await expect(number).toHaveValue('5')
  await page.keyboard.press('End')
  await expect(number).toHaveValue('20')
  await number.fill('21')
  await page.getByRole('button', { name: 'Analyze and continue' }).click()
  expect(state.createBodies).toHaveLength(0)
  await expect(number).toBeFocused()
  await number.fill('20')
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
  await expect(number).toHaveValue('20')
  await number.fill('10')
  await expect(page.getByRole('button', { name: 'Confirm and search' })).toBeDisabled()
  await page.getByRole('button', { name: 'Save changes' }).click()
  await expect(page.getByRole('button', { name: 'Confirm and search' })).toBeEnabled()
  expect(state.requests.at(-1)).toMatchObject({
    action: 'edit_conditions',
    search_options: { result_count: 10 },
    profile_updates: {},
  })
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
  await expect(page.getByLabel('Work location', { exact: true })).toHaveValue(preferences.location)
  const interpreted = page
    .locator('details')
    .filter({ has: page.getByText('How your preferences will be searched', { exact: true }) })
  await expect(interpreted).toHaveAttribute('open', '')
  await expect(interpreted).toContainText('Hong Kong, 深圳')
  await expect(interpreted).toContainText('Excluded: 南山区')
  await interpreted.locator('summary').press('Enter')
  await expect(interpreted).not.toHaveAttribute('open')
  await expect(page.getByLabel('Work location', { exact: true })).toHaveValue(preferences.location)
  await page.getByLabel('Work location', { exact: true }).fill('仅深圳')
  await expect(interpreted).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Confirm and search', exact: true })).toBeDisabled()
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
      analyzed_count: 2,
      matched_count: 1,
      pending_count: 1,
      elapsed_seconds: 28,
      retrieval_stopped: false,
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
  const stop = page.getByRole('button', { name: 'End Search' })
  await expect(stop).toBeEnabled()
  await expect(page.getByRole('list', { name: 'Job search steps' })).toBeVisible()
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
  await expect(stop).toHaveCount(0)
  const polls = state.getCount()
  const finished = structuredClone(running)
  finished.outcome = 'completed'
  finished.current_stage = 'completed'
  finished.stop_reason = 'user_stopped'
  finished.progress = { ...finished.progress, sequence: 4, retrieval_stopped: true }
  finished.recommendation!.pending_jobs[0]!.review_status = 'reviewed'
  state.runFor(1, finished)
  await expect(page.getByRole('button', { name: 'View job: Pending Engineer' })).toContainText(
    'Reviewed',
  )
  expect(state.getCount()).toBeGreaterThan(polls)
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
  await expect(details).toContainText(partial.matching_reasons[0]!.explanation)
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
    await expect(page.getByLabel('Job directions', { exact: true })).toHaveValue(
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
  await page.getByLabel('Skills', { exact: true }).fill('React\nTypeScript')
  await expect(page.getByRole('button', { name: 'Confirm and search' })).toBeDisabled()
  await page.getByRole('button', { name: 'Save changes' }).click()
  await expect(page.getByRole('button', { name: 'Confirm and search' })).toBeEnabled()
  expect(state.requests[1]?.profile_updates).toEqual({ skills: ['React', 'TypeScript'] })
  await page.getByRole('button', { name: 'Confirm and search' }).click()
  await expect(page.getByRole('button', { name: 'View job: React Engineer' })).toBeVisible()
  expect(state.getTimes.length).toBe(2)
  expect(state.getTimes[1]! - state.getTimes[0]!).toBeGreaterThanOrEqual(850)
  const count = state.getCount()
  await page.waitForTimeout(1300)
  expect(state.getCount()).toBe(count)
  await page.getByRole('button', { name: 'View job: React Engineer' }).click()
  await page.getByText('View source excerpts', { exact: true }).click()
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
    'jobscout.session_id': 'session-1',
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

test('reload recovers by ID; running polls once a second and delete prevents restoration', async ({
  page,
}) => {
  const state = await mockSessions(page)
  state.runFor(50, createSessionFixture())
  await introduce(page)
  await expect(page.getByRole('heading', { name: 'Reviewing your experience' })).toBeVisible()
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Reviewing your experience' })).toBeVisible()
  expect(state.createCount()).toBe(1)
  await deleteSearch(page)
  await expect(page.getByRole('button', { name: 'Analyze and continue' })).toBeVisible()
  const count = state.getCount()
  await page.waitForTimeout(1300)
  expect(state.getCount()).toBe(count)
  expect(await page.evaluate(() => localStorage.getItem('jobscout.session_id'))).toBeNull()
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
  await page.getByRole('button', { name: 'Try again' }).click()
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
  await page.getByRole('button', { name: 'Save changes' }).click()
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
  expect(await page.evaluate(() => localStorage.getItem('jobscout.session_id'))).toBeNull()
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
            label: 'Job directions',
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
  const directions = page.getByLabel('Job directions', { exact: true })
  await directions.fill('Frontend development\nData analysis\nProduct design\nSoftware engineering')
  await expect(page.getByRole('button', { name: 'Save changes' })).toBeEnabled()
  await expect(directions).toHaveValue(
    'Frontend development\nData analysis\nProduct design\nSoftware engineering',
  )
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
  await page.getByRole('button', { name: 'Save changes' }).click()
  await expect(page.getByRole('button', { name: 'Confirm and search' })).toBeEnabled()
  await expect(page.getByLabel('Add or correct search criteria', { exact: true })).toHaveValue('')
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

test('long result lists keep selected details reachable and changing jobs resets detail scrolling', async ({
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
  const later = page.getByRole('button', { name: 'View job: Engineer 9', exact: true })
  await later.scrollIntoViewIfNeeded()
  await expect(detail.getByRole('heading', { name: 'Engineer 1', exact: true })).toBeInViewport()
  const pageScroll = await page.evaluate(() => window.scrollY)
  const listing = detail.getByRole('link', { name: 'View job listing', exact: true })
  await listing.focus()
  await page.keyboard.press('PageDown')
  await expect.poll(() => detail.evaluate((element) => element.scrollTop)).toBeGreaterThan(0)
  expect(await page.evaluate(() => window.scrollY)).toBe(pageScroll)
  await later.click()
  await expect(page).toHaveURL(/job=long-list-8/)
  await expect(detail.getByRole('heading', { name: 'Engineer 9', exact: true })).toBeInViewport()
  expect(await detail.evaluate((element) => element.scrollTop)).toBe(0)
  const lastResponsibility = detail.getByText('Engineer 9: supplied responsibility 30.', {
    exact: true,
  })
  await lastResponsibility.scrollIntoViewIfNeeded()
  await expect(lastResponsibility).toBeInViewport()
  await expect(listing).toBeInViewport()
  if (process.env.JOBSCOUT_REVIEW_SCREENSHOTS === '1') {
    await mkdir('.tools/review', { recursive: true })
    await page.screenshot({ path: '.tools/review/results-sticky-desktop.png' })
  }
  await page.setViewportSize({ width: 1440, height: 500 })
  await lastResponsibility.scrollIntoViewIfNeeded()
  await expect(lastResponsibility).toBeInViewport()
  await expect(listing).toBeInViewport()
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
  await expect(page.getByRole('button', { name: 'Try again', exact: true })).toBeVisible()
  for (const item of failed.recommendation!.jobs)
    await expect(
      page.getByRole('button', { name: `View job: ${item.job.title}`, exact: true }),
    ).toBeVisible()
  await expect(page.locator('body')).not.toContainText('private-failure-detail')
  await page.getByRole('button', { name: 'Edit search criteria', exact: true }).click()
  await expect(page.getByLabel('Job directions', { exact: true })).toBeVisible()
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
  await page.getByRole('combobox', { name: 'Filter by listing status' }).selectOption('expired')
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
  for (const summary of await page.locator('details > summary').all()) await summary.click()
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
  const source = page.getByRole('listitem').filter({ hasText: 'Liepin · Frontend development' })
  await expect(source).toBeVisible()
  await expect(detail).not.toContainText('unsupported-preparation-sentinel')
  await expect(detail.getByText(item.notices[0]!.message, { exact: false })).toHaveCount(1)
  const visible = await page.locator('body').innerText()
  for (const internalId of [item.job.job_id, 'private-document-id'])
    expect(visible).not.toContain(internalId)
  await captureResults(page, 'results-expanded-notices')
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
  await page.getByText('Sources and search coverage', { exact: true }).click()
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
  const dialog = page.getByRole('dialog', { name: 'Delete search?', exact: true })
  await dialog.getByRole('button', { name: 'Keep search', exact: true }).click()
  await expect(trigger).toBeFocused()
  expect(deletions).toEqual([])
  await trigger.click()
  await dialog.getByRole('button', { name: 'Delete search', exact: true }).click()
  await expect(dialog.getByRole('alert')).toBeVisible()
  await expect(dialog).not.toContainText('private-deletion-diagnostic')
  await dialog.getByRole('button', { name: 'Keep search', exact: true }).click()
  await expect(trigger).toBeFocused()
  await expect(
    page.getByRole('button', { name: 'Remove saved job: React Engineer', exact: true }),
  ).toBeVisible()
  expect(await page.evaluate(() => localStorage.getItem('jobscout.session_id'))).toBe('session-1')
  await trigger.click()
  await dialog.getByRole('button', { name: 'Delete search', exact: true }).click()
  await expect(page.getByLabel('About you', { exact: true })).toHaveValue(introduction)
  await expect(
    page.getByRole('button', { name: 'Remove resume: original.txt', exact: true }),
  ).toBeVisible()
  expect(deletions).toEqual([deletions[0], deletions[0]])
  expect(await page.evaluate(() => localStorage.getItem('jobscout.session_id'))).toBeNull()
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
    await expect(page.locator('#profile-error').getByRole('alert')).toBeVisible()
    await expect(page.locator('#profile-error').getByRole('alert')).not.toContainText(
      'private-parser-path',
    )
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
  expect(await page.evaluate(() => localStorage.getItem('jobscout.session_id'))).toBeNull()
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
  const initialToggle = await toggle.boundingBox()
  const newSearchIcon = sidebar
    .getByRole('link', { name: 'New search', exact: true })
    .locator('svg')
  const initialIcon = await newSearchIcon.boundingBox()

  for (let cycle = 0; cycle < 3; cycle += 1) {
    await toggle.click()
    await expect(toggle).toHaveAttribute('aria-expanded', 'true')
    await expect(sidebar).toHaveCSS('width', '288px')
    expect(await toggle.boundingBox()).toEqual(initialToggle)
    expect(await newSearchIcon.boundingBox()).toEqual(initialIcon)
    expect(await page.evaluate(() => window.scrollY)).toBe(scrollY)
    await sidebar.getByText('Collapse sidebar', { exact: true }).click()
    await expect(sidebar).toHaveCSS('width', '72px')
    expect(await toggle.boundingBox()).toEqual(initialToggle)
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
