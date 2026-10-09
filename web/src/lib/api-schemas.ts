import * as v from 'valibot'

import type {
  AccountResponse,
  SessionResponse,
  RecommendationItem,
  DraftResponse,
  ModelSettingsResponse,
  DailyUsage,
  DisabledUsage,
  ConnectionResult,
} from '../api/types.gen'

export const vAccountResponse: v.GenericSchema<AccountResponse> = v.object({
  user_id: v.string(),
  username: v.string(),
  csrf_token: v.string(),
  expires_at: v.string(),
})

export const vApplicantError = v.strictObject({
  code: v.string(),
  message: v.string(),
  action: v.nullable(v.picklist(['retry', 'edit_conditions', 'reload', 'start_new_search'])),
})

export const vApplicantNotice = v.strictObject({
  code: v.picklist([
    'source_unavailable',
    'source_partial',
    'coverage_limited',
    'listing_incomplete',
    'listing_status_unverified',
    'preference_unverified',
    'analysis_partial',
    'analysis_unavailable',
  ]),
  scope: v.picklist(['session', 'source', 'job']),
  message: v.string(),
  action: v.nullable(v.picklist(['retry', 'edit_conditions', 'open_listing'])),
  job_id: v.nullable(v.string()),
  source: v.nullable(v.string()),
  preference: v.nullable(v.string()),
})

export const vClarificationStatus = v.picklist(['pending', 'answered', 'skipped'])

export const vConversationResponse = v.strictObject({
  label: v.string(),
  value: v.union([v.string(), v.array(v.string())]),
  status: v.picklist(['answered', 'skipped']),
})

export const vConversationMessage = v.strictObject({
  message_id: v.string(),
  role: v.picklist(['user', 'assistant']),
  text: v.string(),
  responses: v.array(vConversationResponse),
  question_ids: v.array(v.string()),
  created_at: v.pipe(v.string(), v.isoTimestamp()),
})

export const vDraftResponse: v.GenericSchema<DraftResponse> = v.object({
  data: v.record(v.string(), v.unknown()),
  revision: v.pipe(v.number(), v.integer(), v.minValue(0)),
  updated_at: v.nullable(v.pipe(v.string(), v.isoTimestamp())),
})

export const vEmploymentCondition = v.strictObject({
  raw_text: v.nullable(v.string()),
  included: v.array(v.picklist(['full-time', 'part-time', 'internship', 'contract', 'freelance'])),
  excluded: v.array(v.picklist(['full-time', 'part-time', 'internship', 'contract', 'freelance'])),
  unrestricted: v.boolean(),
})

export const vFreshnessStatus = v.picklist(['active', 'expired', 'unknown'])

export const vLocationRef = v.strictObject({
  id: v.string(),
  name: v.string(),
  region: v.picklist(['cn', 'hk']),
  level: v.picklist(['country', 'region', 'city', 'district']),
  parent_id: v.nullable(v.string()),
  ancestor_ids: v.array(v.string()),
  source_codes: v.record(v.string(), v.string()),
  resolution: v.picklist(['resolved', 'ambiguous', 'unsupported']),
})

export const vLocationCondition = v.strictObject({
  raw_text: v.nullable(v.string()),
  included: v.array(vLocationRef),
  excluded: v.array(vLocationRef),
  unrestricted: v.boolean(),
})

export const vProfileSource = v.strictObject({
  resume: v.boolean(),
  description: v.boolean(),
})

export const vQuestionOption = v.strictObject({
  id: v.string(),
  label: v.string(),
})

export const vClarificationMessage = v.strictObject({
  question: v.string(),
  field: v.string(),
  reason: v.string(),
  required: v.boolean(),
  status: vClarificationStatus,
  answer: v.nullable(v.string()),
  question_id: v.string(),
  control_type: v.picklist(['single_choice', 'multiple_choice', 'text']),
  options: v.array(vQuestionOption),
})

export const vResumeInput = v.strictObject({
  name: v.string(),
  text: v.string(),
})

export const vReviewIssue = v.strictObject({
  code: v.picklist([
    'timeout',
    'service_unavailable',
    'invalid_output',
    'unverifiable_claims',
    'insufficient_job_information',
    'incomplete_review',
    'failed',
    'stopped',
    'search_ended',
  ]),
  stage: v.nullable(v.picklist(['jd_analysis', 'matching'])),
})

export const vSearchActivity = v.strictObject({
  sequence: v.pipe(v.number(), v.integer(), v.minValue(1)),
  job_id: v.string(),
  title: v.string(),
  company: v.string(),
  location: v.string(),
  status: v.picklist([
    'found',
    'queued',
    'reviewing',
    'reviewed',
    'summary_reviewed',
    'not_reviewed',
    'partial',
    'timeout',
    'unavailable',
    'invalid',
    'insufficient',
    'failed',
    'excluded',
    'unverified',
    'expired',
    'duplicate',
    'not_shortlisted',
  ]),
  review_issue: v.nullable(vReviewIssue),
  exclusion_reasons: v.array(
    v.picklist(['role', 'location', 'employment_type', 'expired', 'duplicate']),
  ),
  unknown_conditions: v.array(v.string()),
  recommendation_fit: v.picklist(['recommended', 'possible', 'unlikely', 'unknown']),
})

export const vSearchEvent = v.strictObject({
  sequence: v.pipe(v.number(), v.integer(), v.minValue(1)),
  action: v.string(),
  message: v.string(),
  source: v.nullable(v.string()),
})

export const vSearchOptionsOutput = v.strictObject({
  result_count: v.pipe(v.number(), v.integer(), v.minValue(5), v.maxValue(20)),
})

export const vSearchProgress = v.strictObject({
  sequence: v.pipe(v.number(), v.integer(), v.minValue(0)),
  discovered_count: v.pipe(v.number(), v.integer(), v.minValue(0)),
  analyzed_count: v.pipe(v.number(), v.integer(), v.minValue(0)),
  matched_count: v.pipe(v.number(), v.integer(), v.minValue(0)),
  pending_count: v.pipe(v.number(), v.integer(), v.minValue(0)),
  elapsed_seconds: v.pipe(v.number(), v.minValue(0)),
  retrieval_stopped: v.boolean(),
  events: v.array(vSearchEvent),
  activity: v.pipe(v.array(vSearchActivity), v.maxLength(250)),
})

export const vSessionHistoryItem = v.object({
  session_id: v.string(),
  title: v.string(),
  location: v.string(),
  outcome: v.picklist(['queued', 'running', 'paused', 'completed', 'failed', 'cancelled']),
  current_stage: v.string(),
  revision: v.pipe(v.number(), v.integer(), v.minValue(0)),
  created_at: v.pipe(v.string(), v.isoTimestamp()),
  updated_at: v.pipe(v.string(), v.isoTimestamp()),
  retryable: v.boolean(),
  mode: v.picklist(['live', 'replay']),
})

export const vSessionHistoryResponse = v.object({
  items: v.array(vSessionHistoryItem),
  next_cursor: v.nullable(v.string()),
})

export const vSourceDocument = v.strictObject({
  document_id: v.string(),
  source: v.string(),
  source_url: v.string(),
  text: v.string(),
  fetched_at: v.pipe(v.string(), v.isoTimestamp()),
  is_excerpt: v.boolean(),
})

export const vJobPosting = v.strictObject({
  job_id: v.string(),
  source: v.string(),
  source_url: v.string(),
  title: v.string(),
  company: v.string(),
  location: v.string(),
  salary: v.nullable(v.string()),
  target_direction: v.string(),
  responsibilities: v.array(v.string()),
  required_skills: v.array(v.string()),
  posted_at: v.nullable(v.pipe(v.string(), v.isoTimestamp())),
  expiry_at: v.nullable(v.pipe(v.string(), v.isoTimestamp())),
  freshness_status: vFreshnessStatus,
  fetched_at: v.pipe(v.string(), v.isoTimestamp()),
  source_links: v.array(v.string()),
  source_documents: v.array(vSourceDocument),
  description: v.string(),
  description_is_excerpt: v.boolean(),
  employment_type: v.nullable(v.string()),
  target_directions: v.array(v.string()),
})

export const vSourceOutcome = v.object({
  request_index: v.pipe(v.number(), v.integer()),
  target_direction: v.string(),
  source: v.string(),
  candidate_count: v.pipe(v.number(), v.integer()),
  returned_count: v.pipe(v.number(), v.integer()),
  incomplete_count: v.pipe(v.number(), v.integer()),
  excerpt_count: v.pipe(v.number(), v.integer()),
  elapsed_seconds: v.number(),
  status: v.string(),
})

export const vSourceQuoteReference = v.strictObject({
  document_id: v.string(),
  excerpt: v.string(),
  source_url: v.nullable(v.string()),
})

export const vMatchDimension = v.pipe(
  v.strictObject({
    id: v.picklist([
      'skills',
      'responsibilities',
      'experience',
      'seniority',
      'education',
      'preferences',
    ]),
    score: v.nullable(v.pipe(v.number(), v.integer(), v.minValue(0), v.maxValue(100))),
    status: v.picklist(['assessed', 'unknown', 'not_applicable']),
    explanation: v.pipe(v.string(), v.maxLength(800)),
    requirement_ids: v.pipe(v.array(v.string()), v.maxLength(30)),
    profile_fact_ids: v.array(v.string()),
    job_source_quotes: v.pipe(v.array(vSourceQuoteReference), v.maxLength(10)),
    profile_source_quotes: v.pipe(v.array(vSourceQuoteReference), v.maxLength(10)),
    missing_information: v.pipe(v.array(v.string()), v.maxLength(10)),
    weight: v.pipe(v.number(), v.integer(), v.minValue(0), v.maxValue(100)),
    input_hash: v.string(),
  }),
  v.check((dimension) =>
    dimension.status === 'assessed' ? dimension.score !== null : dimension.score === null,
  ),
)

const dimensionIds = [
  'skills',
  'responsibilities',
  'experience',
  'seniority',
  'education',
  'preferences',
] as const

export const vMatchScore = v.pipe(
  v.strictObject({
    total: v.nullable(v.pipe(v.number(), v.integer(), v.minValue(0), v.maxValue(100))),
    dimensions: v.tuple([
      vMatchDimension,
      vMatchDimension,
      vMatchDimension,
      vMatchDimension,
      vMatchDimension,
      vMatchDimension,
    ]),
    assessed_weight: v.pipe(v.number(), v.integer(), v.minValue(0), v.maxValue(100)),
    applicable_weight: v.pipe(v.number(), v.integer(), v.minValue(0), v.maxValue(100)),
    assessed_percentage: v.pipe(v.number(), v.integer(), v.minValue(0), v.maxValue(100)),
    provisional: v.boolean(),
    completeness: v.picklist(['complete', 'partial', 'unknown']),
    input_hash: v.string(),
  }),
  v.check((score) =>
    score.dimensions.every((dimension, index) => dimension.id === dimensionIds[index]),
  ),
)

export const vMatchingReason = v.strictObject({
  requirement: v.string(),
  level: v.picklist(['strong', 'partial', 'related_experience', 'not_documented']),
  explanation: v.string(),
  job_source_quotes: v.array(vSourceQuoteReference),
  profile_source_quotes: v.array(vSourceQuoteReference),
})

export const vRecommendationItem: v.GenericSchema<RecommendationItem> = v.strictObject({
  job: vJobPosting,
  preparation_suggestions: v.array(v.string()),
  matching_reasons: v.array(vMatchingReason),
  notices: v.array(vApplicantNotice),
  analysis_status: v.picklist(['complete', 'partial', 'unavailable']),
  review_status: v.picklist(['queued', 'reviewing', 'reviewed', 'not_reviewed']),
  verification_status: v.picklist(['confirmed', 'pending', 'unknown']),
  unknown_conditions: v.array(v.string()),
  review_issue: v.nullable(vReviewIssue),
  recommendation_fit: v.picklist(['recommended', 'possible', 'unlikely', 'unknown']),
  recommendation_reason: v.string(),
  match_score: v.nullable(vMatchScore),
})

export const vRecommendationResult = v.strictObject({
  session_id: v.string(),
  generated_at: v.pipe(v.string(), v.isoTimestamp()),
  jobs: v.pipe(v.array(vRecommendationItem), v.maxLength(20)),
  pending_jobs: v.pipe(v.array(vRecommendationItem), v.maxLength(20)),
  notices: v.array(vApplicantNotice),
  introduction: v.string(),
})

export const vSavedJobsResponse = v.object({
  items: v.array(vRecommendationItem),
})

export const vWorkArrangement = v.strictObject({
  raw_text: v.nullable(v.string()),
  included: v.array(v.picklist(['remote', 'hybrid', 'onsite'])),
  excluded: v.array(v.picklist(['remote', 'hybrid', 'onsite'])),
  unrestricted: v.boolean(),
  uncertain: v.boolean(),
})

export const vProfilePreferences = v.strictObject({
  location: v.nullable(v.string()),
  location_unrestricted: v.boolean(),
  employment_type: v.nullable(v.string()),
  employment_type_unrestricted: v.boolean(),
  salary_range: v.nullable(v.string()),
  work_mode: v.nullable(v.string()),
  industry: v.nullable(v.string()),
  locations: vLocationCondition,
  employment: vEmploymentCondition,
  work_arrangement: vWorkArrangement,
})

export const vUserProfile = v.strictObject({
  profile_id: v.string(),
  source: vProfileSource,
  education: v.array(v.string()),
  skills: v.array(v.string()),
  internships: v.array(v.string()),
  projects: v.array(v.string()),
  target_directions: v.array(v.string()),
  preferences: vProfilePreferences,
  search_options: vSearchOptionsOutput,
  confirmed_fields: v.array(v.string()),
  missing_required_fields: v.array(v.string()),
  conflicts: v.array(v.string()),
})

export const vSearchSummary = v.strictObject({
  profile: vUserProfile,
  revision: v.pipe(v.number(), v.integer(), v.minValue(0)),
  ready: v.boolean(),
  confirmed: v.boolean(),
  editable_fields: v.array(v.string()),
  missing_fields: v.array(v.string()),
  search_limitations: v.string(),
})

export const vSessionResponse: v.GenericSchema<SessionResponse> = v.strictObject({
  snapshot_version: v.pipe(v.number(), v.integer(), v.minValue(0)),
  operation_id: v.nullable(v.string()),
  queue_position: v.nullable(v.pipe(v.number(), v.integer(), v.minValue(1))),
  enqueued_at: v.nullable(v.pipe(v.string(), v.isoTimestamp())),
  expires_at: v.nullable(v.pipe(v.string(), v.isoTimestamp())),
  session_id: v.string(),
  outcome: v.picklist(['queued', 'running', 'paused', 'completed', 'failed', 'cancelled']),
  current_stage: v.string(),
  revision: v.pipe(v.number(), v.integer(), v.minValue(0)),
  profile: v.nullable(vUserProfile),
  clarification_questions: v.array(vClarificationMessage),
  conversation: v.array(vConversationMessage),
  search_summary: v.nullable(vSearchSummary),
  source_outcomes: v.array(vSourceOutcome),
  recommendation: v.nullable(vRecommendationResult),
  errors: v.array(vApplicantError),
  notices: v.array(vApplicantNotice),
  retryable: v.boolean(),
  mode: v.picklist(['live', 'replay']),
  run_id: v.nullable(v.string()),
  progress: vSearchProgress,
  stop_reason: v.nullable(
    v.picklist([
      'results_ready',
      'target_reached',
      'source_exhausted',
      'budget_exhausted',
      'user_stopped',
      'error',
    ]),
  ),
})

const vModelInfo = v.object({
  personal: v.boolean(),
  endpoint_id: v.nullable(v.string()),
  model: v.string(),
  key_configured: v.boolean(),
  server_provider: v.string(),
  server_model: v.string(),
  server_key_configured: v.boolean(),
  thinking: v.boolean(),
  server_thinking: v.boolean(),
  thinking_level: v.string(),
  server_thinking_level: v.string(),
})
export const vModelSettings: v.GenericSchema<ModelSettingsResponse> = v.object({
  roles: v.object({ semantic: vModelInfo, decision: vModelInfo }),
  endpoints: v.array(
    v.object({
      id: v.string(),
      name: v.string(),
      thinking_supported: v.boolean(),
      thinking_level_supported: v.boolean(),
    }),
  ),
  personal_available: v.boolean(),
})
const nonnegativeInteger = v.pipe(v.number(), v.integer(), v.minValue(0))
export const vUsage: v.GenericSchema<DailyUsage | DisabledUsage> = v.variant('enabled', [
  v.object({ enabled: v.literal(false) }),
  v.object({
    enabled: v.literal(true),
    remaining: nonnegativeInteger,
    used: nonnegativeInteger,
    reserved: nonnegativeInteger,
    limit: nonnegativeInteger,
    server_remaining: nonnegativeInteger,
    day: v.string(),
    timezone: v.string(),
  }),
])
export const vConnectionResult: v.GenericSchema<ConnectionResult> = v.object({
  ok: v.literal(true),
})

export const vResumeLimits = v.strictObject({
  max_bytes: v.pipe(v.number(), v.integer(), v.minValue(1)),
  max_pdf_pages: v.pipe(v.number(), v.integer(), v.minValue(1)),
  max_text_characters: v.pipe(v.number(), v.integer(), v.minValue(1)),
})
