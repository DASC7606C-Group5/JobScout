import type { RecommendationItem, ScoutSession } from './contracts'
import { isMatchScore } from './matching-contracts'

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
function nonnegativeInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0
}
function locationRef(value: unknown) {
  return (
    record(value) &&
    string(value.id) &&
    string(value.name) &&
    member(value.region, ['hk', 'cn']) &&
    member(value.level, ['country', 'region', 'city', 'district']) &&
    nullableString(value.parent_id) &&
    list(value.ancestor_ids, string) &&
    record(value.source_codes) &&
    Object.values(value.source_codes).every(string) &&
    member(value.resolution, ['resolved', 'ambiguous', 'unsupported'])
  )
}
function conditions(value: unknown, item: (entry: unknown) => boolean) {
  return (
    record(value) &&
    nullableString(value.raw_text) &&
    typeof value.unrestricted === 'boolean' &&
    list(value.included, item) &&
    list(value.excluded, item)
  )
}
function profile(value: unknown) {
  if (!record(value) || !record(value.preferences) || !record(value.search_options)) return false
  const preferences = value.preferences
  const count = value.search_options.result_count
  return (
    typeof count === 'number' &&
    Number.isInteger(count) &&
    count >= 5 &&
    count <= 20 &&
    conditions(preferences.locations, locationRef) &&
    conditions(preferences.employment, (value) =>
      member(value, ['full-time', 'part-time', 'internship', 'contract', 'freelance']),
    ) &&
    conditions(preferences.work_arrangement, (value) =>
      member(value, ['remote', 'hybrid', 'onsite']),
    ) &&
    record(preferences.work_arrangement) &&
    typeof preferences.work_arrangement.uncertain === 'boolean'
  )
}
function progress(value: unknown) {
  return (
    record(value) &&
    nonnegativeInteger(value.sequence) &&
    nonnegativeInteger(value.discovered_count) &&
    nonnegativeInteger(value.analyzed_count) &&
    nonnegativeInteger(value.matched_count) &&
    nonnegativeInteger(value.pending_count) &&
    typeof value.elapsed_seconds === 'number' &&
    Number.isFinite(value.elapsed_seconds) &&
    value.elapsed_seconds >= 0 &&
    typeof value.retrieval_stopped === 'boolean' &&
    list(
      value.activity,
      (item) =>
        record(item) &&
        nonnegativeInteger(item.sequence) &&
        item.sequence > 0 &&
        string(item.job_id) &&
        string(item.title) &&
        string(item.company) &&
        string(item.location) &&
        member(item.status, [
          'found',
          'reviewing',
          'reviewed',
          'excluded',
          'not_shortlisted',
          'unverified',
          'unavailable',
          'not_reviewed',
        ]) &&
        member(item.recommendation_fit, ['recommended', 'possible', 'unlikely', 'unknown']),
    ) &&
    list(
      value.events,
      (event) =>
        record(event) &&
        nonnegativeInteger(event.sequence) &&
        string(event.action) &&
        string(event.message) &&
        nullableString(event.source),
    )
  )
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
function sourceQuote(value: unknown) {
  return (
    record(value) &&
    string(value.document_id) &&
    string(value.excerpt) &&
    nullableString(value.source_url)
  )
}
function matchingReason(value: unknown) {
  return (
    record(value) &&
    string(value.requirement) &&
    member(value.level, ['strong', 'partial', 'related_experience', 'not_documented']) &&
    string(value.explanation) &&
    list(value.job_source_quotes, sourceQuote) &&
    list(value.profile_source_quotes, sourceQuote)
  )
}
export function isRecommendationItem(value: unknown): value is RecommendationItem {
  return (
    record(value) &&
    record(value.job) &&
    (value.match_score === null || isMatchScore(value.match_score)) &&
    string(value.job.job_id) &&
    member(value.analysis_status, ['complete', 'partial', 'unavailable']) &&
    member(value.review_status, ['queued', 'reviewing', 'reviewed', 'not_reviewed']) &&
    member(value.verification_status, ['confirmed', 'pending', 'unknown']) &&
    member(value.recommendation_fit, ['recommended', 'possible', 'unlikely', 'unknown']) &&
    string(value.recommendation_reason) &&
    list(value.unknown_conditions, string) &&
    list(value.notices, notice) &&
    list(value.matching_reasons, matchingReason) &&
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
      list(value.jobs, isRecommendationItem) &&
      list(value.pending_jobs, isRecommendationItem))
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
    nullableString(value.run_id) &&
    progress(value.progress) &&
    (value.stop_reason === null ||
      member(value.stop_reason, [
        'results_ready',
        'target_reached',
        'source_exhausted',
        'budget_exhausted',
        'user_stopped',
        'error',
      ])) &&
    (value.profile === null || profile(value.profile)) &&
    (value.search_summary === null ||
      (record(value.search_summary) && profile(value.search_summary.profile))) &&
    Array.isArray(value.clarification_questions) &&
    Array.isArray(value.source_outcomes) &&
    list(value.conversation, conversation) &&
    list(value.notices, notice) &&
    list(value.errors, error) &&
    recommendation(value.recommendation)
  )
}
