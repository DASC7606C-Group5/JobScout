// Mirrors src/jobscout/schemas. Keep wire-format field names intact.
export type EmploymentType = 'full-time' | 'part-time' | 'internship' | 'contract' | 'freelance'
export type WorkMode = 'remote' | 'hybrid' | 'onsite'

export interface WorkArrangement {
  raw_text: string | null
  included: WorkMode[]
  excluded: WorkMode[]
  unrestricted: boolean
  uncertain: boolean
}

export interface LocationRef {
  id: string
  name: string
  region: 'hk' | 'cn'
  level: 'country' | 'region' | 'city' | 'district'
  parent_id: string | null
  ancestor_ids: string[]
  source_codes: Record<string, string>
  resolution: 'resolved' | 'ambiguous' | 'unsupported'
}

export interface LocationCondition {
  raw_text: string | null
  included: LocationRef[]
  excluded: LocationRef[]
  unrestricted: boolean
}

export interface EmploymentCondition {
  raw_text: string | null
  included: EmploymentType[]
  excluded: EmploymentType[]
  unrestricted: boolean
}

export interface SearchOptions {
  result_count: number
}

export interface RawPreferences {
  location: string | null
  location_unrestricted: boolean
  employment_type: string | null
  employment_type_unrestricted: boolean
  salary_range: string | null
  work_mode: string | null
  industry: string | null
}

export interface ProfilePreferences extends RawPreferences {
  locations: LocationCondition
  employment: EmploymentCondition
  work_arrangement: WorkArrangement
}

export interface UserProfile {
  profile_id: string
  source: { resume: boolean; description: boolean }
  education: string[]
  skills: string[]
  internships: string[]
  projects: string[]
  target_directions: string[]
  preferences: ProfilePreferences
  search_options: SearchOptions
  confirmed_fields: string[]
  missing_required_fields: string[]
  conflicts: string[]
}

export interface ClarificationMessage {
  question: string
  field: string
  reason: string
  required: boolean
  status: 'pending' | 'answered' | 'skipped'
  answer: string | null
  question_id: string
  control_type: 'single_choice' | 'multiple_choice' | 'text'
  options: { id: string; label: string }[]
}

export interface ConversationMessage {
  message_id: string
  role: 'user' | 'assistant'
  text: string
  question_ids: string[]
  created_at: string
  responses: ConversationResponse[]
}

export interface ConversationResponse {
  label: string
  value: string | string[]
  status: 'answered' | 'skipped'
}

export interface SearchSummary {
  profile: UserProfile
  revision: number
  ready: boolean
  confirmed: boolean
  editable_fields: string[]
  missing_fields: string[]
  coverage_notice: string
}

export interface SourceQuoteReference {
  document_id: string
  excerpt: string
  source_url: string | null
}

export interface MatchingReason {
  requirement: string
  level: 'strong' | 'partial' | 'related_experience' | 'not_documented'
  explanation: string
  job_source_quotes: SourceQuoteReference[]
  profile_source_quotes: SourceQuoteReference[]
}

export interface SourceOutcome {
  request_index: number
  target_direction: string
  source: string
  candidate_count: number
  returned_count: number
  incomplete_count: number
  excerpt_count: number
  elapsed_seconds: number
  status: string
}

export interface JobPosting {
  job_id: string
  source: string
  source_url: string
  source_links: string[]
  title: string
  company: string
  location: string
  salary: string | null
  target_direction: string
  responsibilities: string[]
  required_skills: string[]
  posted_at: string | null
  expiry_at: string | null
  fetched_at: string
  freshness_status: 'active' | 'expired' | 'unknown'
  source_documents: {
    document_id: string
    source: string
    source_url: string
    text: string
    fetched_at: string
    is_excerpt: boolean
  }[]
  description: string
  description_is_excerpt: boolean
  employment_type: string | null
  target_directions: string[]
}

export interface RecommendationItem {
  job: JobPosting
  preparation_suggestions: string[]
  matching_reasons: MatchingReason[]
  notices: ApplicantNotice[]
  analysis_status: 'complete' | 'partial' | 'unavailable'
  verification_status: 'confirmed' | 'pending' | 'unknown'
  unknown_conditions: string[]
  recommendation_fit: 'recommended' | 'possible' | 'unlikely' | 'unknown'
  recommendation_reason: string
}

export interface RecommendationResult {
  session_id: string
  generated_at: string
  jobs: RecommendationItem[]
  pending_jobs: RecommendationItem[]
  introduction: string
  notices: ApplicantNotice[]
}

export interface ApplicantNotice {
  code: string
  scope: 'session' | 'source' | 'job'
  message: string
  action: 'retry' | 'edit_conditions' | 'open_listing' | null
  job_id: string | null
  source: string | null
  preference: string | null
}

export type ApplicantRecovery = 'retry' | 'edit_conditions' | 'reload' | 'start_new_search' | null

export interface ApplicantError {
  code: string
  message: string
  action: ApplicantRecovery
}

// Mirrors src/jobscout/schemas/session.py.
export interface ScoutInput {
  description: string
  resume: { name: string; text: string } | null
  target_directions: string[]
  preferences: RawPreferences
  search_options: SearchOptions
}

export type CreateSessionRequest = ScoutInput & { request_id: string }
export interface QuestionAnswer {
  question_id: string
  value: string | string[]
}
export interface ResumeSessionRequest {
  request_id: string
  expected_revision: number
  message: string
  answers: QuestionAnswer[]
  skipped_question_ids: string[]
  action: 'answer' | 'confirm_search' | 'edit_conditions' | 'retry'
  profile_updates: Record<string, string | string[] | boolean | null>
  search_options?: SearchOptions | null
}
export type ResumeSubmission = Omit<ResumeSessionRequest, 'request_id' | 'expected_revision'>

export interface StopSessionRequest {
  request_id: string
  expected_revision: number
  run_id: string
}

export type StopReason =
  | 'results_ready'
  | 'target_reached'
  | 'source_exhausted'
  | 'budget_exhausted'
  | 'user_stopped'
  | 'error'

export interface SearchEvent {
  sequence: number
  action: string
  message: string
  source: string | null
}

export interface SearchProgress {
  sequence: number
  analyzed_count: number
  matched_count: number
  pending_count: number
  elapsed_seconds: number
  events: SearchEvent[]
}

export interface ScoutSession {
  session_id: string
  profile: UserProfile | null
  outcome: 'running' | 'paused' | 'completed' | 'failed'
  current_stage: string
  revision: number
  run_id: string | null
  progress: SearchProgress
  stop_reason: StopReason | null
  clarification_questions: ClarificationMessage[]
  conversation: ConversationMessage[]
  search_summary: SearchSummary | null
  source_outcomes: SourceOutcome[]
  recommendation: RecommendationResult | null
  errors: ApplicantError[]
  notices: ApplicantNotice[]
  retryable: boolean
  mode: 'live' | 'replay'
}

export interface SessionClient {
  start: (input: CreateSessionRequest, signal?: AbortSignal) => Promise<ScoutSession>
  get: (sessionId: string, signal?: AbortSignal) => Promise<ScoutSession>
  answer: (
    sessionId: string,
    request: ResumeSessionRequest,
    signal?: AbortSignal,
  ) => Promise<ScoutSession>
  delete: (sessionId: string, signal?: AbortSignal) => Promise<void>
  stop: (
    sessionId: string,
    request: StopSessionRequest,
    signal?: AbortSignal,
  ) => Promise<ScoutSession>
}

export interface SessionSummary {
  session_id: string
  title: string
  location: string
  created_at: string
  updated_at: string
  outcome: ScoutSession['outcome']
  current_stage: string
  revision: number
  retryable: boolean
  mode: ScoutSession['mode']
}

export interface SessionHistory {
  items: SessionSummary[]
  next_cursor: string | null
}

export interface DraftResponse<T = Record<string, unknown>> {
  data: T
  revision: number
  updated_at: string | null
}

export interface SaveDraftRequest<T = Record<string, unknown>> {
  data: T
  request_id: string
  expected_revision: number
}

export type DraftSection = 'clarification' | 'summary'

export interface WorkspaceClient {
  history: (cursor: string | null, signal?: AbortSignal) => Promise<SessionHistory>
  getDraft: (path: string, signal?: AbortSignal) => Promise<DraftResponse>
  saveDraft: (path: string, request: SaveDraftRequest) => Promise<DraftResponse>
  savedJobs: (signal?: AbortSignal) => Promise<RecommendationItem[]>
  saveJob: (jobId: string, sessionId: string, revision: number) => Promise<RecommendationItem>
  removeJob: (jobId: string) => Promise<void>
}
