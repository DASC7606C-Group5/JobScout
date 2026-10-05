// Mirrors src/jobscout/schemas. Keep wire-format field names intact.
export interface ProfilePreferences {
  location: string | null
  location_unrestricted: boolean
  employment_type: string | null
  employment_type_unrestricted: boolean
  salary_range: string | null
  work_mode: string | null
  industry: string | null
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
}

export interface RecommendationResult {
  session_id: string
  generated_at: string
  jobs: RecommendationItem[]
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
  preferences: ProfilePreferences
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
}
export type ResumeSubmission = Omit<ResumeSessionRequest, 'request_id' | 'expected_revision'>

export interface ScoutSession {
  session_id: string
  profile: UserProfile | null
  outcome: 'running' | 'paused' | 'completed' | 'failed'
  current_stage: string
  revision: number
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
}
