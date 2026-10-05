import type { ScoutSession } from './contracts'

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}
function string(value: unknown): value is string {
  return typeof value === 'string'
}
function nullableString(value: unknown) {
  return value === null || string(value)
}
function list(value: unknown, valid: (item: unknown) => boolean) {
  return Array.isArray(value) && value.every(valid)
}
function member(value: unknown, choices: string[]) {
  return string(value) && choices.includes(value)
}
function recovery(value: unknown) {
  return value === null || member(value, ['retry', 'edit_conditions', 'reload', 'start_new_search'])
}

function notice(value: unknown) {
  return (
    record(value) &&
    string(value.code) &&
    string(value.message) &&
    member(value.scope, ['session', 'source', 'job']) &&
    (value.action === null || member(value.action, ['retry', 'edit_conditions', 'open_listing'])) &&
    nullableString(value.job_id) &&
    nullableString(value.source) &&
    nullableString(value.preference)
  )
}
function response(value: unknown) {
  return (
    record(value) &&
    string(value.label) &&
    member(value.status, ['answered', 'skipped']) &&
    (string(value.value) || list(value.value, string))
  )
}
function conversation(value: unknown) {
  return (
    record(value) &&
    string(value.message_id) &&
    member(value.role, ['user', 'assistant']) &&
    string(value.text) &&
    string(value.created_at) &&
    list(value.question_ids, string) &&
    list(value.responses, response)
  )
}
function error(value: unknown) {
  return record(value) && string(value.code) && string(value.message) && recovery(value.action)
}
function recommendationItem(value: unknown) {
  return (
    record(value) &&
    record(value.job) &&
    string(value.job.job_id) &&
    member(value.analysis_status, ['complete', 'partial', 'unavailable']) &&
    list(value.notices, notice) &&
    Array.isArray(value.matching_reasons) &&
    list(value.preparation_suggestions, string)
  )
}
function recommendation(value: unknown) {
  return (
    value === null ||
    (record(value) &&
      string(value.session_id) &&
      string(value.generated_at) &&
      string(value.introduction) &&
      list(value.notices, notice) &&
      list(value.jobs, recommendationItem))
  )
}
function sessionIdentity(value: Record<string, unknown>) {
  return (
    string(value.session_id) &&
    member(value.outcome, ['running', 'paused', 'completed', 'failed']) &&
    Number.isInteger(value.revision) &&
    typeof value.revision === 'number' &&
    value.revision >= 0 &&
    string(value.current_stage) &&
    member(value.mode, ['live', 'replay']) &&
    typeof value.retryable === 'boolean'
  )
}

export function isSessionResponse(value: unknown): value is ScoutSession {
  return (
    record(value) &&
    sessionIdentity(value) &&
    (value.profile === null || record(value.profile)) &&
    (value.search_summary === null || record(value.search_summary)) &&
    Array.isArray(value.clarification_questions) &&
    Array.isArray(value.source_outcomes) &&
    list(value.conversation, conversation) &&
    list(value.notices, notice) &&
    list(value.errors, error) &&
    recommendation(value.recommendation)
  )
}
