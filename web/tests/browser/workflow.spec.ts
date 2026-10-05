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
  question: `${question_id} 问题`,
  reason: '用于完善搜索条件',
  field: 'skills',
  status: 'pending',
  answer: null,
  options: [
    { id: 'one-id', label: '选项一' },
    { id: 'two-id', label: '选项二' },
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
          introduction: '根据已确认的条件，以下岗位供你核对。',
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
            text: body.message || '已更新回答',
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
  await page.getByLabel('个人介绍', { exact: true }).fill('合成测试资料：React 开发经历。')
  await page.getByRole('button', { name: '开始分析与对话' }).click()
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
  await expect(page.getByText('回放演示模式', { exact: false })).toBeVisible()
  await expect(page.getByLabel('hidden 问题', { exact: true })).toHaveCount(0)
  await page.getByRole('radio', { name: '选项一' }).focus()
  await page.keyboard.press('Space')
  await page.getByRole('checkbox', { name: '选项一', exact: true }).check()
  await page.getByRole('checkbox', { name: '选项二', exact: true }).check()
  await page.getByRole('checkbox', { name: '跳过此问题' }).check()
  await page.getByLabel('补充或纠正', { exact: true }).fill('更正：我接受不限地点。')
  await page.getByRole('button', { name: '发送并继续' }).click()
  await expect(page.getByRole('heading', { name: '确认你的画像与搜索条件' })).toBeVisible()
  expect(state.requests[0]).toMatchObject({
    action: 'answer',
    expected_revision: 1,
    answers: [
      { question_id: 'single', value: 'one-id' },
      { question_id: 'multiple', value: ['one-id', 'two-id'] },
    ],
    skipped_question_ids: ['optional'],
    message: '更正：我接受不限地点。',
  })
  await expect(page.getByText('已跳过（选填）', { exact: false })).toBeVisible()
  expect(state.requests.some((request) => request.action === 'confirm_search')).toBe(false)
  await page.getByLabel('技能', { exact: true }).fill('React\nTypeScript')
  await expect(page.getByRole('button', { name: '确认并开始搜索' })).toBeDisabled()
  await page.getByRole('button', { name: '保存修改' }).click()
  await expect(page.getByRole('button', { name: '确认并开始搜索' })).toBeEnabled()
  expect(state.requests[1]?.profile_updates).toEqual({ skills: ['React', 'TypeScript'] })
  await page.getByRole('button', { name: '确认并开始搜索' }).click()
  await expect(page.getByRole('heading', { name: 'React Engineer' })).toBeVisible()
  expect(state.getTimes.length).toBe(2)
  expect(state.getTimes[1]! - state.getTimes[0]!).toBeGreaterThanOrEqual(850)
  const count = state.getCount()
  await page.waitForTimeout(1300)
  expect(state.getCount()).toBe(count)
  await expect(
    page.locator('details').filter({ has: page.getByText('查看对话历史', { exact: true }) }),
  ).not.toHaveAttribute('open')
  await page.getByText('岗位详情与准备建议', { exact: true }).click()
  await expect(page.getByRole('heading', { name: '匹配理由与证据' })).toBeVisible()
  await expect(page.getByText('“React development experience required.”')).toBeVisible()
  await expect(
    page.getByText('这仅表示所提供材料中未找到证据，并不代表你不具备该能力。'),
  ).toBeVisible()
  await page.getByRole('button', { name: '收藏React Engineer', exact: true }).click()
  await page.getByRole('link', { name: '收藏岗位', exact: false }).first().click()
  await expect(page.getByRole('heading', { name: 'React Engineer' })).toBeVisible()
  await page.getByRole('link', { name: '发现机会', exact: false }).first().click()
  await page.getByRole('button', { name: '调整求职条件' }).click()
  await expect(page.getByRole('heading', { name: '确认你的画像与搜索条件' })).toBeVisible()
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
  await expect(page.getByText('无法连接服务', { exact: false })).toBeVisible()
  await page.getByRole('button', { name: '重试', exact: true }).click()
  await expect(page.getByRole('button', { name: '确认并开始搜索' })).toBeEnabled()
  expect(state.createBodies[0]?.request_id).toBe(state.createBodies[1]?.request_id)
  state.conflictNext()
  await page.getByRole('button', { name: '确认并开始搜索' }).click()
  await expect.poll(state.getCount).toBe(1)
  await expect(page.getByRole('button', { name: '确认并开始搜索' })).toBeEnabled()
  await page.getByRole('button', { name: '确认并开始搜索' }).click()
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
  await expect(page.getByRole('heading', { name: '正在理解你的经历' })).toBeVisible()
  await page.reload()
  await expect(page.getByRole('heading', { name: '正在理解你的经历' })).toBeVisible()
  expect(state.createCount()).toBe(1)
  await page.getByRole('button', { name: '清除会话' }).click()
  await expect(page.getByRole('button', { name: '开始分析与对话' })).toBeVisible()
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
        { code: 'MODEL_UNAVAILABLE', stage: 'extract', message: '模型暂不可用', details: null },
      ],
    }),
  )
  await introduce(page)
  await page.getByRole('button', { name: '重新尝试' }).click()
  await expect(page.getByRole('heading', { name: '确认你的画像与搜索条件' })).toBeVisible()
  expect(state.requests[0]?.action).toBe('retry')
  expect(state.createCount()).toBe(1)
})

test('resume-only input is valid and disclosure is present; required text control accepts free text', async ({
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
  await page.goto('/')
  await expect(
    page.getByText('个人介绍和简历文本将发送给后端配置的模型服务商', { exact: false }),
  ).toBeVisible()
  await page.getByRole('button', { name: '开始分析与对话' }).click()
  await expect(page.getByText('请填写个人介绍，或添加一份简历。')).toBeVisible()
  await page.locator('input[type=file]').setInputFiles({
    name: 'synthetic.txt',
    mimeType: 'text/plain',
    buffer: Buffer.from('Synthetic React project, no real personal data.'),
  })
  await page.getByRole('button', { name: '开始分析与对话' }).click()
  await page.getByLabel('text 问题', { exact: true }).fill('香港')
  await page.getByRole('button', { name: '发送并继续' }).click()
  await expect(page.getByRole('button', { name: '确认并开始搜索' })).toBeEnabled()
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
  await page.getByLabel('补充或纠正', { exact: true }).fill('只使用补充文字更新条件')
  await page.getByRole('button', { name: '发送并继续' }).click()
  await expect(page.getByText('无法连接服务', { exact: false })).toBeVisible()
  await expect(page.getByLabel('补充或纠正', { exact: true })).toHaveValue('只使用补充文字更新条件')
  await page.getByRole('button', { name: '重试', exact: true }).click()
  await expect(page.getByRole('button', { name: '确认并开始搜索' })).toBeEnabled()
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
  await expect(page.getByRole('button', { name: '确认并开始搜索' })).toBeDisabled()
  await page.getByRole('checkbox', { name: '不限地点', exact: true }).check()
  await page.getByRole('button', { name: '保存修改' }).click()
  await expect(page.getByRole('button', { name: '确认并开始搜索' })).toBeEnabled()
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
  await expect(page.getByRole('button', { name: '确认并开始搜索' })).toBeDisabled()
  await expect(page.getByText('摘要版本已过期，请刷新会话后再确认搜索。')).toBeVisible()
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
  await expect(page.getByText('会话已不存在', { exact: false })).toBeVisible()
  await page.getByRole('button', { name: '重新开始', exact: true }).click()
  await expect(page.getByRole('button', { name: '开始分析与对话' })).toBeEnabled()
  expect(await page.evaluate(() => sessionStorage.getItem('jobscout.session_id'))).toBeNull()
})

test('empty result and source outage remain distinct without invented vacancies', async ({
  page,
}) => {
  const outcome = {
    request_index: 0,
    target_direction: '前端开发',
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
        warnings: ['一个来源暂不可用'],
        introduction: '没有可验证的合适岗位。',
      },
      source_outcomes: [
        { ...outcome, source: 'JobsDB', status: 'ok' },
        { ...outcome, source: 'Liepin', status: 'blocked' },
      ],
    }),
  )
  await introduce(page)
  await page.getByText('检索来源与覆盖情况', { exact: true }).click()
  await expect(
    page.getByText('JobsDB · 前端开发：检索成功，无结果', { exact: false }),
  ).toBeVisible()
  await expect(page.getByText('Liepin · 前端开发：访问受限', { exact: false })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'React Engineer' })).toHaveCount(0)
})
