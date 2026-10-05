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
  expect(
    presentConversation(
      message(
        "测试\ntarget_directions: ['技术/研发', '产品/项目']\npreferences.location: 不限\npreferences.employment_type: full-time\n备注: 使用 [React]。",
      ),
    ),
  ).toEqual({
    text: '测试\n备注: 使用 [React]。',
    responses: [
      { label: '求职方向', value: ['技术/研发', '产品/项目'], status: 'answered' },
      { label: '工作地点', value: '不限', status: 'answered' },
      { label: '工作类型', value: '全职', status: 'answered' },
    ],
  })
})

test('legacy unrestricted updates produce one meaningful row and safely decode quoted lists', () => {
  expect(
    presentConversation(
      message(
        "projects: ['O\\'Brien project', 'React, SQL']\npreferences.location: None\npreferences.location_unrestricted: True",
      ),
    ).responses,
  ).toEqual([
    { label: '项目经历', value: ["O'Brien project", 'React, SQL'], status: 'answered' },
    { label: '工作地点', value: '不限', status: 'answered' },
  ])
})

test('new structured messages preserve free text and skipped answers', () => {
  const structured: ConversationMessage = {
    ...message('仍然希望做前端开发。'),
    responses: [
      { label: '求职方向', value: ['前端开发'], status: 'answered' },
      { label: '行业偏好', value: '', status: 'skipped' },
    ],
  }
  expect(presentConversation(structured)).toEqual({
    text: structured.text,
    responses: structured.responses ?? [],
  })
  expect(presentConversation({ ...message('skills: 请补充技能。'), role: 'assistant' }).text).toBe(
    'skills: 请补充技能。',
  )
  expect(presentConversation({ ...message('skills: Python'), responses: [] })).toEqual({
    text: 'skills: Python',
    responses: [],
  })
})

test('answer history resolves option IDs while direction validation preserves all choices', () => {
  expect(presentQuestionAnswer({ ...question('skill'), answer: 'react-id' })).toEqual(['React'])
  const directions = { ...question('directions'), field: 'target_directions' }
  const four = ['a', 'b', 'c', 'd']
  expect(answerValidation([directions], { directions: four }, [])).toContain('最多选择三个')
  expect(answerValidation([directions], { directions: four.slice(0, 3) }, [])).toBe('')
  expect(
    answerValidation([directions], { directions: '前端开发\n数据分析\n产品设计\n软件工程' }, []),
  ).toContain('最多选择三个')
  expect(four).toEqual(['a', 'b', 'c', 'd'])
})
