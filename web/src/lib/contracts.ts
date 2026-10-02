// Mirrors src/jobscout/schemas (Schema v1). Keep wire-format field names intact.
export interface ProfilePreferences {
  location: string | null
  location_unrestricted: boolean
  employment_type: string | null
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
  status: 'pending' | 'answered'
  answer: string | null
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
}

export interface RecommendationItem {
  job: JobPosting
  missing_skills: string[]
  preparation_suggestions: string[]
}

export interface RecommendationResult {
  session_id: string
  generated_at: string
  jobs: RecommendationItem[]
  warnings: string[]
}

export interface WorkflowError {
  code: string
  message: string
  stage: string
  details: Record<string, string | number | boolean | null> | null
}

// Frontend adapter models, NOT a frozen HTTP Session API contract.
export interface ScoutInput {
  description: string
  resume: { name: string; text: string } | null
  target_directions: string[]
  preferences: ProfilePreferences
}

export type DemoScenario = 'normal' | 'clarify' | 'empty' | 'error'

export interface ScoutSession {
  session_id: string
  profile: UserProfile
  current_stage: 'clarify' | 'completed' | 'failed'
  clarification_questions: ClarificationMessage[]
  recommendation: RecommendationResult | null
  errors: WorkflowError[]
}

export interface SessionClient {
  start: (input: ScoutInput, scenario: DemoScenario) => Promise<ScoutSession>
  answer: (
    session: ScoutSession,
    answers: Record<string, string>,
    scenario: DemoScenario,
  ) => Promise<ScoutSession>
  retry: (session: ScoutSession) => Promise<ScoutSession>
}
