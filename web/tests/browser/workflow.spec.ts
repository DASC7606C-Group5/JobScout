import { mkdir } from 'node:fs/promises'

import { expect, test, type Page } from '@playwright/test'

import type {
  ClarificationMessage,
  ResumeSessionRequest,
  ScoutSession,
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
  let getCount = 0
  let createCount = 0
  const getTimes: number[] = []
  const requests: ResumeSessionRequest[] = []
  const createBodies: Record<string, unknown>[] = []
  let dropCreate = false
  let dropAnswer = false
  let conflict = false
  let runningPolls = 0
  let finish = snapshot
  await page.route('**/api/v1/sessions**', async (route) => {
    const method = route.request().method()
    if (method === 'DELETE') {
      await route.fulfill({ status: 204 })
      return
    }
    if (method === 'GET') {
      getCount += 1
      getTimes.push(Date.now())
      if (runningPolls > 0 && --runningPolls === 0) snapshot = finish
      await route.fulfill({ json: snapshot })
      return
    }
    if (!route.request().url().endsWith('/resume')) {
      createCount += 1
      createBodies.push(route.request().postDataJSON() as Record<string, unknown>)
      if (dropCreate) {
        dropCreate = false
        await route.abort('failed')
        return
      }
      await route.fulfill({ status: 202, json: snapshot })
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
        },
      }
      snapshot = { ...snapshot, revision, outcome: 'running', current_stage: 'search' }
      runningPolls = 2
    } else {
      const profile = structuredClone(snapshot.profile ?? createSessionFixture().profile)!
      for (const [key, value] of Object.entries(body.profile_updates)) {
        if (key === 'skills' && Array.isArray(value)) profile.skills = value
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
    await route.fulfill({ status: 202, json: snapshot })
  })
  return {
    requests,
    createBodies,
    getTimes,
    getCount: () => getCount,
    createCount: () => createCount,
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
      runningPolls = polls
      finish = final
    },
  }
}

async function introduce(page: Page) {
  await page.goto('/')
  await page
    .getByLabel('About you', { exact: true })
    .fill('Synthetic test profile: React development experience.')
  await page.getByRole('button', { name: 'Analyze and continue' }).click()
}

test('three-step flow uses IDs, explicit confirmation, evidence, saved jobs and same-session edits', async ({
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
  await page.getByRole('radio', { name: 'Option one' }).focus()
  await page.keyboard.press('Space')
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
  await page.getByText('View supporting evidence', { exact: true }).click()
  await expect(page.getByText('“React development experience required.”')).toBeVisible()
  await page.getByRole('button', { name: 'Save job: React Engineer', exact: true }).click()
  await page.getByRole('link', { name: 'Saved jobs', exact: false }).first().click()
  await expect(page.getByRole('button', { name: 'View job: React Engineer' })).toBeVisible()
  await page.getByRole('link', { name: 'Explore opportunities', exact: false }).first().click()
  await page.getByRole('button', { name: 'Edit search criteria' }).click()
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
  expect(storage).toEqual({ local: {}, session: { 'jobscout.session_id': 'session-1' } })
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
  await page.getByRole('button', { name: 'Start a new search', exact: true }).click()
  await page
    .getByRole('dialog')
    .getByRole('button', { name: 'Start a new search', exact: true })
    .click()
  await expect(page.getByRole('button', { name: 'Analyze and continue' })).toBeVisible()
  const count = state.getCount()
  await page.waitForTimeout(1300)
  expect(state.getCount()).toBe(count)
  expect(await page.evaluate(() => sessionStorage.getItem('jobscout.session_id'))).toBeNull()
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
  await page.goto('/')
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

test('expired recovered session offers a fresh start without persisting private material', async ({
  page,
}) => {
  await page.addInitScript(() => sessionStorage.setItem('jobscout.session_id', 'expired'))
  await page.route('**/api/v1/sessions/expired', (route) =>
    route.fulfill({
      status: 404,
      json: {
        detail: {
          code: 'search_not_found',
          message: 'Search unavailable.',
          action: 'start_new_search',
        },
      },
    }),
  )
  await page.goto('/')
  await page.getByRole('button', { name: 'Start over', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Analyze and continue' })).toBeEnabled()
  expect(await page.evaluate(() => sessionStorage.getItem('jobscout.session_id'))).toBeNull()
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
  await page.getByRole('link', { name: 'Explore opportunities', exact: false }).first().click()
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

test('direction choices enforce three selections without dropping user choices', async ({
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
  ).toBeDisabled()
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
  ).toBeEnabled()
  expect(state.requests).toEqual([])
})

test('summary edits survive navigation, local overflow preserves entries and new revision clears message', async ({
  page,
}) => {
  const state = await mockSessions(page)
  await introduce(page)
  const directions = page.getByLabel('Job directions (up to 3)', { exact: true })
  await directions.fill('Frontend development\nData analysis\nProduct design\nSoftware engineering')
  await expect(page.getByRole('button', { name: 'Save changes' })).toBeDisabled()
  await expect(directions).toHaveValue(
    'Frontend development\nData analysis\nProduct design\nSoftware engineering',
  )
  await directions.fill('Frontend development')
  await page.getByLabel('Skills', { exact: true }).fill('React\nSQL')
  await page
    .getByLabel('Add or correct search criteria', { exact: true })
    .fill('I’d like mentorship.')
  await page.getByRole('link', { name: 'Saved jobs', exact: false }).first().click()
  await expect(page).toHaveURL(/\/saved$/)
  await page.getByRole('link', { name: 'Explore opportunities', exact: false }).first().click()
  await expect(page.getByLabel('Skills', { exact: true })).toHaveValue('React\nSQL')
  await expect(page.getByLabel('Add or correct search criteria', { exact: true })).toHaveValue(
    'I’d like mentorship.',
  )
  await page.getByRole('button', { name: 'Save changes' }).click()
  await expect(page.getByRole('button', { name: 'Confirm and search' })).toBeEnabled()
  await expect(page.getByLabel('Add or correct search criteria', { exact: true })).toHaveValue('')
  expect(state.requests[0]?.profile_updates).toEqual({ skills: ['React', 'SQL'] })
  expect(await page.evaluate(() => Object.keys(sessionStorage))).toEqual(['jobscout.session_id'])
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
  await page.getByRole('button', { name: 'Explore opportunities', exact: true }).click()
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

test('expanded notices expose only applicant content and incomplete analysis retains the listing', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1100 })
  const session = resultSession()
  const item = session.recommendation!.jobs[0]!
  item.job.job_id = 'gen-private-id'
  item.matching_reasons[0]!.job_evidence[0]!.document_id = 'private-document-id'
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
      source: 'Liepin',
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
  item.matching_reasons[0]!.profile_evidence[0]!.excerpt = 'I worked on Group 6 using Python.'
  session.source_outcomes = [
    {
      request_index: 0,
      target_direction: 'Frontend development',
      source: 'Liepin',
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
    detail.getByText(`“${item.matching_reasons[0]!.profile_evidence[0]!.excerpt}”`, {
      exact: true,
    }),
  ).toBeVisible()
  await expect(page.getByText(session.notices[1]!.message, { exact: true })).toBeVisible()
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
  empty.notices = [
    {
      code: 'source_unavailable',
      scope: 'source',
      source: 'Liepin',
      job_id: null,
      preference: null,
      message: 'Liepin is unavailable. You can try another search later.',
      action: null,
    },
  ]
  const state = await mockSessions(page, empty)
  await introduce(page)
  await expect(page.getByRole('article', { name: 'Job details', exact: true })).toHaveCount(0)
  await page.getByText('About this search', { exact: true }).click()
  await captureResults(page, 'results-empty')
  await page.getByRole('button', { name: 'Edit search criteria', exact: true }).last().click()
  await expect(page.getByRole('button', { name: 'Confirm and search' })).toBeEnabled()
  expect(state.requests.at(-1)?.action).toBe('edit_conditions')
})

test('invalid selected deep links recover to the list and service failure allows a corrected search', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 900 })
  await page.addInitScript(() => sessionStorage.setItem('jobscout.session_id', 'session-1'))
  await mockSessions(page, resultSession())
  await page.goto('/?job=discarded-record&freshness=not-a-status')
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
  await page.reload()
  await expect(page.getByRole('button', { name: 'Try again', exact: true })).toHaveCount(0)
  await expect(page.locator('body')).not.toContainText('SOURCE_CONFIG_MISSING')
  await captureResults(page, 'search-service-failure')
  await page.getByRole('button', { name: 'Edit search criteria', exact: true }).last().click()
  await expect(page.getByRole('button', { name: 'Confirm and search' })).toBeEnabled()
  expect(state.requests.at(-1)?.action).toBe('edit_conditions')
})

test('starting over requires confirmation and a failed deletion preserves the search and private drafts', async ({
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
    else await route.fulfill({ status: 204 })
  })
  await page.goto('/')
  const introduction = 'Original introduction: React 项目 experience.'
  await page.getByLabel('About you', { exact: true }).fill(introduction)
  await page.locator('input[type=file]').setInputFiles({
    name: 'original.txt',
    mimeType: 'text/plain',
    buffer: Buffer.from('Original resume contents'),
  })
  await page.getByRole('button', { name: 'Analyze and continue' }).click()
  await page.getByRole('button', { name: 'Save job: React Engineer', exact: true }).click()
  const trigger = page.getByRole('button', { name: 'Start a new search', exact: true }).first()
  await trigger.click()
  const dialog = page.getByRole('dialog')
  await dialog.getByRole('button', { name: 'Keep this search', exact: true }).click()
  await expect(trigger).toBeFocused()
  expect(deletions).toEqual([])
  await trigger.click()
  await dialog.getByRole('button', { name: 'Start a new search', exact: true }).click()
  await expect(dialog.getByRole('alert')).toBeVisible()
  await expect(dialog).not.toContainText('private-deletion-diagnostic')
  await dialog.getByRole('button', { name: 'Keep this search', exact: true }).click()
  await expect(trigger).toBeFocused()
  await expect(
    page.getByRole('button', { name: 'Remove saved job: React Engineer', exact: true }),
  ).toBeVisible()
  expect(await page.evaluate(() => sessionStorage.getItem('jobscout.session_id'))).toBe('session-1')
  await trigger.click()
  await dialog.getByRole('button', { name: 'Start a new search', exact: true }).click()
  await expect(page.getByLabel('About you', { exact: true })).toHaveValue(introduction)
  await expect(
    page.getByRole('button', { name: 'Remove resume: original.txt', exact: true }),
  ).toBeVisible()
  expect(deletions).toEqual([deletions[0], deletions[0]])
  expect(await page.evaluate(() => sessionStorage.getItem('jobscout.session_id'))).toBeNull()
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
  await page.goto('/')
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
  await page.getByRole('button', { name: 'Start a new search', exact: true }).click()
  await page
    .getByRole('dialog')
    .getByRole('button', { name: 'Start a new search', exact: true })
    .click()
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
  expect(await page.evaluate(() => sessionStorage.getItem('jobscout.session_id'))).toBeNull()
})
