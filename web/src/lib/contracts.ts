import type {
  SessionStopRequest as StopSessionRequest,
  SessionCreateRequest,
  SessionResumeRequest,
  SessionResponse,
  DraftWriteRequest,
  DraftResponse as ApiDraftResponse,
  EmploymentCondition,
  RawProfilePreferences,
  SearchOptionsOutput,
  SessionHistoryResponse,
  RecommendationItem,
  ConversationMessage,
  QuestionAnswer,
} from '../api/types.gen'

export type ResultReaction = 'interested' | 'not_interested'
export type JobFeedback = {
  job_id: string
  reaction: ResultReaction
  reason: string | null
  updated_at: string
}
export type ResultExclusion = {
  exclusion_id: string
  description: string
  user_message_id: string
}
export type ResultPreferences = {
  preferred_features: string[]
  exclusions: ResultExclusion[]
}
export type HiddenJobReason = {
  job_id: string
  kind: 'not_interested' | 'excluded'
  exclusion_id: string | null
}
export type ResultOperationKind = 'initial_search' | 'follow_up'
export type FeedbackRequest = {
  request_id: string
  expected_revision: number
  job_id: string
  reaction: ResultReaction | null
}
export type FollowUpRequest =
  | {
      request_id: string
      expected_revision: number
      action: 'message'
      job_id?: string | null
      message: string
    }
  | {
      request_id: string
      expected_revision: number
      action: 'find_similar'
      job_id: string
      message?: string
    }
  | {
      request_id: string
      expected_revision: number
      action: 'answer'
      answers: QuestionAnswer[]
      skipped_question_ids?: string[]
      message?: string
    }
export type ResultConversationMessage = ConversationMessage & { job_id: string | null }
export type FollowUpSubmission =
  | Omit<Extract<FollowUpRequest, { action: 'message' }>, 'request_id' | 'expected_revision'>
  | Omit<Extract<FollowUpRequest, { action: 'find_similar' }>, 'request_id' | 'expected_revision'>
  | Omit<Extract<FollowUpRequest, { action: 'answer' }>, 'request_id' | 'expected_revision'>

export type {
  WorkArrangement,
  LocationRef,
  LocationCondition,
  EmploymentCondition,
  ProfilePreferences,
  UserProfile,
  ClarificationMessage,
  ConversationMessage,
  ConversationResponse,
  SearchSummary,
  SourceQuoteReference,
  MatchingReason,
  SourceOutcome,
  JobPosting,
  RecommendationItem,
  RecommendationResult,
  ApplicantNotice,
  ApplicantError,
  QuestionAnswer,
  SearchEvent,
  SearchActivity,
  SearchProgress,
  SessionHistoryItem as SessionSummary,
  SessionStopRequest as StopSessionRequest,
} from '../api/types.gen'

export type EmploymentType = EmploymentCondition['included'][number]
export type SearchOptions = SearchOptionsOutput
export type RawPreferences = Required<RawProfilePreferences>
export type ApplicantRecovery = import('../api/types.gen').ApplicantError['action']
export type ScoutInput = Required<
  Omit<SessionCreateRequest, 'request_id' | 'preferences' | 'search_options'>
> & { preferences: RawPreferences; search_options: SearchOptions }
export type CreateSessionRequest = ScoutInput & Pick<SessionCreateRequest, 'request_id'>
export type ResumeSessionRequest = Required<
  Omit<SessionResumeRequest, 'search_options' | 'profile_updates'>
> & {
  profile_updates: NonNullable<SessionResumeRequest['profile_updates']>
  search_options?: SearchOptions | null
}
export type ResumeSubmission = Omit<ResumeSessionRequest, 'request_id' | 'expected_revision'>
export type ScoutSession = SessionResponse
export type ResultSession = SessionResponse
export type SessionHistory = SessionHistoryResponse
export type DraftResponse<T = Record<string, unknown>> = Omit<ApiDraftResponse, 'data'> & {
  data: T
}
export type SaveDraftRequest<T = Record<string, unknown>> = Omit<DraftWriteRequest, 'data'> & {
  data: T
}
export type DraftSection = 'clarification' | 'summary'

export interface SessionClient {
  start: (input: CreateSessionRequest, signal?: AbortSignal) => Promise<ScoutSession>
  get: (sessionId: string, signal?: AbortSignal) => Promise<ScoutSession>
  subscribe: (
    sessionId: string,
    handlers: {
      onSnapshot: (session: ScoutSession) => void
      onError: (error: Error) => void
    },
  ) => () => void
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
  feedback: (
    sessionId: string,
    request: FeedbackRequest,
    signal?: AbortSignal,
  ) => Promise<ScoutSession>
  followUp: (
    sessionId: string,
    request: FollowUpRequest,
    signal?: AbortSignal,
  ) => Promise<ScoutSession>
}

export interface WorkspaceClient {
  history: (cursor: string | null, signal?: AbortSignal) => Promise<SessionHistory>
  getDraft: (path: string, signal?: AbortSignal) => Promise<DraftResponse>
  saveDraft: (path: string, request: SaveDraftRequest) => Promise<DraftResponse>
  savedJobs: (signal?: AbortSignal) => Promise<RecommendationItem[]>
  saveJob: (jobId: string, sessionId: string, revision: number) => Promise<RecommendationItem>
  removeJob: (jobId: string) => Promise<void>
}
