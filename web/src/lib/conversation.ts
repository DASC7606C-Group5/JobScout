import type { ClarificationMessage, QuestionAnswer } from './contracts'

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
