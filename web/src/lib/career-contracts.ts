import type { RecommendationItem } from './contracts'

export type SourceDocument = {
  document_id: string
  source: string
  source_url: string
  text: string
  fetched_at: string
  is_excerpt: boolean
}
export type Background = {
  education: string[]
  skills: string[]
  internships: string[]
  projects: string[]
}
export type PersonalProfile = {
  expected_revision: number
  revision: number
  updated_at: string | null
  description: string
  resume: { name: string; text: string } | null
  background: Background
  documents: SourceDocument[]
}
export type ProfileWrite = Omit<PersonalProfile, 'revision' | 'updated_at'>
export type Interest = 'neutral' | 'interested' | 'not_interested'
export type FeedbackWrite = { interest: Interest; reason: string; scope: 'job' | 'task' }
export type TaskJobFeedback = FeedbackWrite & {
  session_id: string
  job_id: string
  item: RecommendationItem
  updated_at: string
}
export type ApplicationStage = 'not_applied' | 'applied' | 'interview' | 'closed'
export type ApplicationWrite = { stage: ApplicationStage; note: string; session_id?: string }
export type JobApplication = {
  job_id: string
  stage: ApplicationStage
  note: string
  item: RecommendationItem
  created_at: string
  updated_at: string
  history: { stage: ApplicationStage; note: string; changed_at: string }[]
}
