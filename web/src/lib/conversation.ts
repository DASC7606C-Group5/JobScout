import type { ClarificationMessage, QuestionAnswer } from './contracts'

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
export function profileFieldLabel(field: string) {
  return fieldLabels[field] ?? field
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
