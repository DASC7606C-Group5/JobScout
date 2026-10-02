import type {
  ClarificationMessage,
  DemoScenario,
  ScoutInput,
  ScoutSession,
  SessionClient,
  UserProfile,
} from './contracts'
import { demoJobs } from './demo-jobs'

const questionFor = (field: string, question: string, reason: string): ClarificationMessage => ({
  field,
  question,
  reason,
  required: true,
  status: 'pending',
  answer: null,
})

function profileFrom(input: ScoutInput): UserProfile {
  const missing: string[] = []
  if (!input.target_directions.length) missing.push('target_directions')
  if (!input.preferences.location?.trim() && !input.preferences.location_unrestricted)
    missing.push('preferences.location')
  if (!input.preferences.employment_type) missing.push('preferences.employment_type')
  return {
    profile_id: crypto.randomUUID(),
    source: { resume: Boolean(input.resume), description: Boolean(input.description.trim()) },
    education: [],
    skills: [],
    internships: [],
    projects: [],
    target_directions: [...input.target_directions],
    preferences: { ...input.preferences },
    confirmed_fields: [],
    missing_required_fields: missing,
    conflicts: [],
  }
}

const questions: Record<string, ClarificationMessage> = {
  target_directions: questionFor(
    'target_directions',
    '你希望寻找哪一类岗位？',
    '求职方向用于确定搜索范围；多个方向可以用逗号分隔。',
  ),
  'preferences.location': questionFor(
    'preferences.location',
    '你希望在哪个城市工作？',
    '请填写城市；如果没有地点偏好，可以回答“不限”。',
  ),
  'preferences.employment_type': questionFor(
    'preferences.employment_type',
    '你更倾向哪种工作类型？',
    '例如全职、实习或兼职，以便筛选合适的机会。',
  ),
  'preferences.work_mode': questionFor(
    'preferences.work_mode',
    '你对工作方式有什么偏好？',
    '可以选择办公室、混合办公、远程，或者不限。',
  ),
}

function finish(session: ScoutSession, scenario: DemoScenario): ScoutSession {
  if (scenario === 'error')
    return {
      ...session,
      current_stage: 'failed',
      recommendation: null,
      errors: [
        {
          code: 'SEARCH_UNAVAILABLE',
          stage: 'search',
          message: '暂时无法获取岗位信息，你的求职条件已保留。',
          details: null,
        },
      ],
    }
  return {
    ...session,
    current_stage: 'completed',
    errors: [],
    recommendation: {
      session_id: session.session_id,
      generated_at: new Date().toISOString(),
      jobs: scenario === 'empty' ? [] : structuredClone(demoJobs),
      warnings:
        scenario === 'empty'
          ? []
          : [
              '以下为固定示例岗位，未按个人资料进行真实匹配。岗位状态、薪资和技能建议均为演示内容。',
            ],
    },
  }
}

// Replace this adapter after Session HTTP endpoints and upload formats are agreed.
// The default adapter never sends personal data or resumes over the network.
export function createDemoClient(delayMs = 1100): SessionClient {
  const pause = () => new Promise<void>((resolve) => setTimeout(resolve, delayMs))
  return {
    async start(input, scenario) {
      await pause()
      const profile = profileFrom(input)
      if (
        scenario === 'clarify' &&
        !profile.missing_required_fields.includes('preferences.work_mode')
      ) {
        profile.missing_required_fields.push('preferences.work_mode')
      }
      const pending = profile.missing_required_fields.flatMap((field) =>
        questions[field] ? [{ ...questions[field] }] : [],
      )
      const session: ScoutSession = {
        session_id: crypto.randomUUID(),
        profile,
        current_stage: 'clarify',
        clarification_questions: pending,
        recommendation: null,
        errors: [],
      }
      return pending.length ? session : finish(session, scenario)
    },
    async answer(session, answers, scenario) {
      await pause()
      const next = structuredClone(session)
      for (const question of next.clarification_questions) {
        const answer = answers[question.field]?.trim()
        if (question.status === 'answered' || !answer) continue
        if (question.field === 'target_directions')
          next.profile.target_directions = answer
            .split(/[,，、]/)
            .map((part) => part.trim())
            .filter(Boolean)
        else if (question.field === 'preferences.location') {
          next.profile.preferences.location_unrestricted = answer === '不限'
          next.profile.preferences.location = answer === '不限' ? null : answer
        } else if (question.field === 'preferences.employment_type') {
          next.profile.preferences.employment_type =
            (
              { 全职: 'full-time', 实习: 'internship', 兼职: 'part-time' } as Record<string, string>
            )[answer] ?? answer
        } else if (question.field === 'preferences.work_mode') {
          const workModes: Record<string, string> = {
            办公室: 'onsite',
            混合办公: 'hybrid',
            远程: 'remote',
          }
          next.profile.preferences.work_mode =
            answer === '不限' ? null : (workModes[answer] ?? answer)
        }
        if (question.field === 'target_directions' && !next.profile.target_directions.length)
          continue
        question.status = 'answered'
        question.answer = answer
        next.profile.confirmed_fields.push(question.field)
      }
      next.profile.missing_required_fields = next.clarification_questions
        .filter((question) => question.required && question.status === 'pending')
        .map((question) => question.field)
      return next.profile.missing_required_fields.length ? next : finish(next, scenario)
    },
    async retry(session) {
      await pause()
      return finish(session, 'normal')
    },
  }
}

export const sessionClient = createDemoClient()

export async function readResume(file: File): Promise<ScoutInput['resume']> {
  if (!file.name.toLowerCase().endsWith('.txt'))
    throw new Error('当前支持 TXT 文本简历；PDF / Word 请先复制文字到个人介绍中。')
  if (file.size > 1024 * 1024) throw new Error('文件过大，请选择 1 MB 以内的 TXT 简历。')
  const text = (await file.text()).trim()
  if (!text) throw new Error('这份文件没有文字，请检查后重新选择。')
  if (text.includes('\u0000') || text.includes('\uFFFD'))
    throw new Error('无法读取文件编码，请使用 UTF-8 格式的 TXT 文件。')
  return { name: file.name, text }
}
