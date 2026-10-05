import { expect, test } from 'bun:test'

import type { ClarificationMessage, ConversationMessage } from './contracts'
import {
  answerValidation,
  collectAnswers,
  pendingQuestions,
  presentConversation,
  presentQuestionAnswer,
} from './conversation'

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

const message = (text: string): ConversationMessage => ({
  message_id: 'user-1',
  role: 'user',
  text,
  question_ids: [],
  created_at: '2026-10-03T00:00:00Z',
})

test('legacy evidence lines become human-readable answers without changing ordinary user text', () => {
  const presented = presentConversation(
    message(
      "测试\ntarget_directions: ['技术/研发', '产品/项目']\npreferences.location: location-sentinel\n备注: 使用 [React]。",
    ),
  )
  expect(presented.text).toBe('测试\n备注: 使用 [React]。')
  expect(presented.responses.map(({ value, status }) => ({ value, status }))).toEqual([
    { value: ['技术/研发', '产品/项目'], status: 'answered' },
    { value: 'location-sentinel', status: 'answered' },
  ])
})

test('legacy unrestricted updates produce one meaningful row and safely decode quoted lists', () => {
  const presented = presentConversation(
    message(
      "projects: ['O\\'Brien project', 'React, SQL']\npreferences.location: stale-location\npreferences.location_unrestricted: True",
    ),
  )
  expect(presented.responses).toHaveLength(2)
  expect(presented.responses[0]).toMatchObject({
    value: ["O'Brien project", 'React, SQL'],
    status: 'answered',
  })
  expect(presented.responses.map(({ value }) => value)).not.toContain('stale-location')
})

test('new structured messages preserve free text and skipped answers', () => {
  const structured: ConversationMessage = {
    ...message('仍然希望做前端开发。'),
    responses: [
      { label: 'Job directions', value: ['前端开发'], status: 'answered' },
      { label: 'Industry', value: '', status: 'skipped' },
    ],
  }
  expect(presentConversation(structured)).toEqual({
    text: structured.text,
    responses: structured.responses ?? [],
  })
  expect(
    presentConversation({ ...message('skills: Please add your skills.'), role: 'assistant' }).text,
  ).toBe('skills: Please add your skills.')
  expect(presentConversation({ ...message('skills: Python'), responses: [] })).toEqual({
    text: 'skills: Python',
    responses: [],
  })
})

test('answer history resolves option IDs while direction validation preserves all choices', () => {
  expect(presentQuestionAnswer({ ...question('skill'), answer: 'react-id' })).toEqual(['React'])
  const directions = { ...question('directions'), field: 'target_directions' }
  const four = ['a', 'b', 'c', 'd']
  expect(answerValidation([directions], { directions: four }, [])).not.toBe('')
  expect(answerValidation([directions], { directions: four.slice(0, 3) }, [])).toBe('')
  expect(
    answerValidation([directions], { directions: '前端开发\n数据分析\n产品设计\n软件工程' }, []),
  ).not.toBe('')
  expect(four).toEqual(['a', 'b', 'c', 'd'])
})
