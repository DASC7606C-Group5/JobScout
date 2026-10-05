import type {
  ClarificationMessage,
  ConversationMessage,
  ConversationResponse,
  QuestionAnswer,
} from './contracts'
import { parseDirections } from './profile-form'

const fieldLabels: Record<string, string> = {
  education: '教育背景',
  skills: '技能',
  internships: '实习经历',
  projects: '项目经历',
  target_directions: '求职方向',
  'preferences.location': '工作地点',
  'preferences.location_unrestricted': '工作地点',
  'preferences.employment_type': '工作类型',
  'preferences.employment_type_unrestricted': '工作类型',
  'preferences.salary_range': '期望薪资',
  'preferences.work_mode': '工作方式',
  'preferences.industry': '行业',
}
const preferenceLabels: Record<string, string> = {
  'full-time': '全职',
  'part-time': '兼职',
  internship: '实习',
  contract: '合约制',
  freelance: '自由职业',
  onsite: '办公室',
  hybrid: '混合办公',
  remote: '远程',
  unrestricted: '不限',
}

export function profileFieldLabel(field: string) {
  return fieldLabels[field] ?? field
}

function quotedList(value: string): string[] | null {
  if (!value.startsWith('[') || !value.endsWith(']')) return null
  const content = value.slice(1, -1).trim()
  if (!content) return []
  const result: string[] = []
  let index = 0
  while (index < content.length) {
    while (/\s/.test(content[index] ?? '') && index < content.length) index += 1
    const quote = content[index++]
    if (quote !== "'" && quote !== '"') return null
    let item = ''
    let closed = false
    while (index < content.length) {
      const character = content[index++]
      if (character === quote) {
        closed = true
        break
      }
      if (character === '\\' && index < content.length) {
        const escaped = content[index++]
        item += escaped === 'n' ? '\n' : escaped === 't' ? '\t' : escaped
      } else item += character
    }
    if (!closed) return null
    result.push(item)
    while (/\s/.test(content[index] ?? '') && index < content.length) index += 1
    if (index < content.length && content[index++] !== ',') return null
  }
  return result
}

function legacyValue(field: string, value: string): string | string[] {
  const list = quotedList(value)
  if (list) return list
  if (field.endsWith('_unrestricted'))
    return ['true', 'True'].includes(value) ? '不限' : '有指定偏好'
  if (['None', 'null'].includes(value)) return '未填写'
  return field === 'preferences.employment_type' || field === 'preferences.work_mode'
    ? (preferenceLabels[value] ?? value)
    : value
}

// Older snapshots placed evidence field/value lines in user messages. Interpret only known
// profile keys; ordinary free text, including colons and brackets, stays untouched.
export function presentConversation(message: ConversationMessage) {
  if (message.role !== 'user' || message.responses !== undefined)
    return { text: message.text, responses: message.responses ?? [] }
  const text: string[] = []
  const legacy: { field: string; value: string }[] = []
  for (const line of message.text.split('\n')) {
    const match = /^\s*([\w.]+):\s*(.*)$/.exec(line)
    const field = match?.[1]
    if (field && Object.hasOwn(fieldLabels, field))
      legacy.push({ field, value: match?.[2]?.trim() ?? '' })
    else text.push(line)
  }
  const unrestricted = new Set(
    legacy
      .filter(
        ({ field, value }) => field.endsWith('_unrestricted') && ['true', 'True'].includes(value),
      )
      .map(({ field }) => field.replace('_unrestricted', '')),
  )
  const responses: ConversationResponse[] = legacy
    .filter(({ field }) => !unrestricted.has(field))
    .map(({ field, value }) => ({
      label: profileFieldLabel(field),
      value: legacyValue(field, value),
      status: 'answered',
    }))
  return { text: text.join('\n').trim(), responses }
}

export function presentQuestionAnswer(question: ClarificationMessage) {
  if (!question.answer) return '已回答'
  const selected = question.answer.split(',').map((value) => value.trim())
  const labels = selected.map(
    (value) => question.options.find((option) => option.id === value)?.label,
  )
  if (labels.length && labels.every((label) => typeof label === 'string')) return labels
  return legacyValue(question.field, question.answer)
}

export function answerValidation(
  questions: ClarificationMessage[],
  values: Record<string, string | string[]>,
  skipped: string[],
) {
  const skippedIds = new Set(skipped)
  for (const question of questions) {
    if (question.field !== 'target_directions' || skippedIds.has(question.question_id)) continue
    const value = values[question.question_id]
    const count = Array.isArray(value) ? value.length : parseDirections(value ?? '').length
    if (count > 3) return '最多选择三个求职方向，请减少方向后再发送。'
  }
  return ''
}

export function pendingQuestions(questions: ClarificationMessage[]) {
  return questions.filter((question) => question.status === 'pending').slice(0, 3)
}

export function collectAnswers(
  questions: ClarificationMessage[],
  values: Record<string, string | string[]>,
  skipped: string[],
): QuestionAnswer[] {
  const skippedIds = new Set(skipped)
  return questions.flatMap((question) => {
    if (skippedIds.has(question.question_id)) return []
    const raw = values[question.question_id]
    const value = typeof raw === 'string' ? raw.trim() : raw
    return value?.length ? [{ question_id: question.question_id, value }] : []
  })
}
