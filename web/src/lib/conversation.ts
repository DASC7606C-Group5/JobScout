import type {
  ClarificationMessage,
  ConversationMessage,
  ConversationResponse,
  QuestionAnswer,
} from './contracts'
import { parseDirections } from './profile-form'

const fieldLabels: Record<string, string> = {
  education: 'Education',
  skills: 'Skills',
  internships: 'Internships',
  projects: 'Projects',
  target_directions: 'Job directions',
  'preferences.location': 'Work location',
  'preferences.location_unrestricted': 'Work location',
  'preferences.employment_type': 'Employment type',
  'preferences.employment_type_unrestricted': 'Employment type',
  'preferences.salary_range': 'Expected salary',
  'preferences.work_mode': 'Work arrangement',
  'preferences.industry': 'Industry',
}
const preferenceLabels: Record<string, string> = {
  'full-time': 'Full-time',
  'part-time': 'Part-time',
  internship: 'Internship',
  contract: 'Contract',
  freelance: 'Freelance',
  onsite: 'On-site',
  hybrid: 'Hybrid',
  remote: 'Remote',
  unrestricted: 'No preference',
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
    return ['true', 'True'].includes(value) ? 'No preference' : 'Preference specified'
  if (['None', 'null'].includes(value)) return 'Not provided'
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
  if (!question.answer) return 'Answered'
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
    if (count > 3) return 'Choose no more than three job directions. Remove some before continuing.'
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
