import { expect, test } from 'bun:test'

import type { ClarificationMessage } from './contracts'
import { collectAnswers, pendingQuestions } from './conversation'

const question = (
  id: string,
  status: ClarificationMessage['status'] = 'pending',
): ClarificationMessage => ({
  question_id: id,
  question: id,
  field: 'skills',
  reason: '',
  required: false,
  status,
  answer: null,
  control_type: 'multiple_choice',
  options: [{ id: 'react-id', label: 'React' }],
})

test('only three pending backend questions are displayed; skipped never reappears', () => {
  const pending = pendingQuestions([
    question('old', 'answered'),
    question('skip', 'skipped'),
    ...['a', 'b', 'c', 'd'].map((id) => question(id)),
  ])
  expect(pending.map((entry) => entry.question_id)).toEqual(['a', 'b', 'c'])
})

test('answers carry question and option IDs; empty or skipped answers are omitted', () => {
  expect(
    collectAnswers(
      ['a', 'b', 'c', 'd'].map((id) => question(id)),
      {
        a: ['react-id'],
        b: '  free text  ',
        c: 'must not submit',
        d: '  ',
      },
      ['c'],
    ),
  ).toEqual([
    { question_id: 'a', value: ['react-id'] },
    { question_id: 'b', value: 'free text' },
  ])
})

test('direction answers preserve more than three choices and free-text directions', () => {
  const directions = { ...question('directions'), field: 'target_directions' }
  const four = ['a', 'b', 'c', 'd']
  expect(collectAnswers([directions], { directions: four }, [])).toEqual([
    { question_id: 'directions', value: four },
  ])
  expect(
    collectAnswers([directions], { directions: '前端开发\n数据分析\n产品设计\n软件工程' }, []),
  ).toEqual([{ question_id: 'directions', value: '前端开发\n数据分析\n产品设计\n软件工程' }])
})
