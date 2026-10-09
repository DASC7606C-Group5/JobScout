import type {
  SessionCancelRequest as CancelSessionRequest,
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
} from '../api/types.gen'

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
  SessionCancelRequest as CancelSessionRequest,
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
  cancel: (
    sessionId: string,
    request: CancelSessionRequest,
    signal?: AbortSignal,
  ) => Promise<ScoutSession>
  delete: (sessionId: string, signal?: AbortSignal) => Promise<void>
  stop: (
    sessionId: string,
    request: StopSessionRequest,
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
