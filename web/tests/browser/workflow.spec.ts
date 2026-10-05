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
      await route.fulfill({ status: 409, json: { detail: 'stale_revision' } })
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
          warnings: [],
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
  await expect(page.getByText('Replay demo', { exact: false })).toBeVisible()
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
  await expect(page.getByText('Skipped (optional)', { exact: false })).toBeVisible()
  expect(state.requests.some((request) => request.action === 'confirm_search')).toBe(false)
  await page.getByLabel('Skills', { exact: true }).fill('React\nTypeScript')
  await expect(page.getByRole('button', { name: 'Confirm and search' })).toBeDisabled()
  await page.getByRole('button', { name: 'Save changes' }).click()
  await expect(page.getByRole('button', { name: 'Confirm and search' })).toBeEnabled()
  expect(state.requests[1]?.profile_updates).toEqual({ skills: ['React', 'TypeScript'] })
  await page.getByRole('button', { name: 'Confirm and search' }).click()
  await expect(page.getByRole('heading', { name: 'React Engineer' })).toBeVisible()
  expect(state.getTimes.length).toBe(2)
  expect(state.getTimes[1]! - state.getTimes[0]!).toBeGreaterThanOrEqual(850)
  const count = state.getCount()
  await page.waitForTimeout(1300)
  expect(state.getCount()).toBe(count)
  await expect(
    page
      .locator('details')
      .filter({ has: page.getByText('View conversation history', { exact: true }) }),
  ).not.toHaveAttribute('open')
  await page.getByText('Job details and preparation tips', { exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Match reasons and evidence' })).toBeVisible()
  await expect(page.getByText('“React development experience required.”')).toBeVisible()
  await expect(
    page.getByText(
      'This means the evidence wasn’t found in the materials you shared; it doesn’t mean you lack this skill.',
    ),
  ).toBeVisible()
  await page.getByRole('button', { name: 'Save job: React Engineer', exact: true }).click()
  await page.getByRole('link', { name: 'Saved jobs', exact: false }).first().click()
  await expect(page.getByRole('heading', { name: 'React Engineer' })).toBeVisible()
  await page.getByRole('link', { name: 'Explore opportunities', exact: false }).first().click()
  await page.getByRole('button', { name: 'Edit search criteria' }).click()
  await expect(
    page.getByRole('heading', { name: 'Review your profile and search criteria' }),
  ).toBeVisible()
  await expect(page.getByRole('heading', { name: 'React Engineer' })).toHaveCount(0)
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
  await expect(page.getByText('Could not connect to the service', { exact: false })).toBeVisible()
  await page.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Confirm and search' })).toBeEnabled()
  expect(state.createBodies[0]?.request_id).toBe(state.createBodies[1]?.request_id)
  state.conflictNext()
  await page.getByRole('button', { name: 'Confirm and search' }).click()
  await expect.poll(state.getCount).toBe(1)
  await expect(page.getByRole('button', { name: 'Confirm and search' })).toBeEnabled()
  await page.getByRole('button', { name: 'Confirm and search' }).click()
  await expect(page.getByRole('heading', { name: 'React Engineer' })).toBeVisible()
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
  await page.getByRole('button', { name: 'Clear session' }).click()
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
          code: 'MODEL_UNAVAILABLE',
          stage: 'extract',
          message: 'Model temporarily unavailable',
          details: null,
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
  await expect(page.getByText('Could not connect to the service', { exact: false })).toBeVisible()
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
  await page.getByRole('checkbox', { name: 'I’m open to any location', exact: true }).check()
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
  await expect(
    page.getByText(
      'This summary is out of date. Refresh the session before confirming your search.',
    ),
  ).toBeVisible()
  expect(state.requests).toEqual([])
})

test('expired recovered session offers a fresh start without persisting private material', async ({
  page,
}) => {
  await page.addInitScript(() => sessionStorage.setItem('jobscout.session_id', 'expired'))
  await page.route('**/api/v1/sessions/expired', (route) =>
    route.fulfill({ status: 404, json: { detail: 'not found' } }),
  )
  await page.goto('/')
  await expect(page.getByText('no longer available', { exact: false })).toBeVisible()
  await page.getByRole('button', { name: 'Start over', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Analyze and continue' })).toBeEnabled()
  expect(await page.evaluate(() => sessionStorage.getItem('jobscout.session_id'))).toBeNull()
})

test('empty result and source outage remain distinct without invented vacancies', async ({
  page,
}) => {
  const outcome = {
    request_index: 0,
    target_direction: 'Frontend development',
    candidate_count: 0,
    returned_count: 0,
    incomplete_count: 0,
    excerpt_count: 0,
    elapsed_seconds: 1,
  }
  await mockSessions(
    page,
    createSessionFixture({
      outcome: 'completed',
      current_stage: 'completed',
      recommendation: {
        session_id: 'session-1',
        generated_at: '2026-10-03T00:00:00Z',
        jobs: [],
        warnings: ['One source is temporarily unavailable.'],
        introduction: 'No suitable jobs with verifiable evidence were found.',
      },
      source_outcomes: [
        { ...outcome, source: 'JobsDB', status: 'ok' },
        { ...outcome, source: 'Liepin', status: 'blocked' },
      ],
    }),
  )
  await introduce(page)
  await page.getByText('Sources and search coverage', { exact: true }).click()
  await expect(
    page.getByText('JobsDB · Frontend development: Search complete, no results', { exact: false }),
  ).toBeVisible()
  await expect(
    page.getByText('Liepin · Frontend development: Access restricted', { exact: false }),
  ).toBeVisible()
  await expect(page.getByRole('heading', { name: 'React Engineer' })).toHaveCount(0)
})

test('conversation renders structured and recovered answers without wire-format keys or JSON', async ({
  page,
}) => {
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
        question_ids: [],
        created_at: '2026-10-03T00:00:00Z',
      },
      {
        message_id: 'legacy-user',
        role: 'user',
        text: "测试\ntarget_directions: ['技术/研发', '产品/项目']\npreferences.location: 不限\npreferences.employment_type: full-time",
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
  await expect(history).toContainText('Job directions')
  await expect(history).toContainText('技术/研发')
  await expect(history).toContainText('Full-time')
  await expect(history).toContainText('我希望有导师指导。')
  await expect(history).toContainText('Skipped (optional)')
  await expect(history).not.toContainText('target_directions')
  await expect(history).not.toContainText('preferences.')
  await expect(history).not.toContainText("['")
  await expect(history.locator('dl')).toHaveCount(2)
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
  await expect(page.getByText('Choose up to three directions · 3 / 3 selected')).toBeVisible()
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
