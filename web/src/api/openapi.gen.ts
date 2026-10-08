export interface paths {
  '/api/v1/resumes/parse': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Parse Resume Upload */
    post: operations['parse_resume_upload_api_v1_resumes_parse_post']
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/health': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** Health Check */
    get: operations['health_check_api_v1_health_get']
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/sessions': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** Get History */
    get: operations['get_history_api_v1_sessions_get']
    put?: never
    /** Create Session */
    post: operations['create_session_api_v1_sessions_post']
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/sessions/{session_id}': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** Get Session */
    get: operations['get_session_api_v1_sessions__session_id__get']
    put?: never
    post?: never
    /** Delete Session */
    delete: operations['delete_session_api_v1_sessions__session_id__delete']
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/sessions/{session_id}/events': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** Session Events */
    get: operations['session_events_api_v1_sessions__session_id__events_get']
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/sessions/{session_id}/resume': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Resume Session */
    post: operations['resume_session_api_v1_sessions__session_id__resume_post']
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/sessions/{session_id}/stop': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Stop Session */
    post: operations['stop_session_api_v1_sessions__session_id__stop_post']
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/workspace/draft': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** Get Workspace Draft */
    get: operations['get_workspace_draft_api_v1_workspace_draft_get']
    /** Save Workspace Draft */
    put: operations['save_workspace_draft_api_v1_workspace_draft_put']
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/sessions/{session_id}/drafts/{revision}/{section}': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** Get Session Draft */
    get: operations['get_session_draft_api_v1_sessions__session_id__drafts__revision___section__get']
    /** Save Session Draft */
    put: operations['save_session_draft_api_v1_sessions__session_id__drafts__revision___section__put']
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/saved-jobs': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** Get Saved Jobs */
    get: operations['get_saved_jobs_api_v1_saved_jobs_get']
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/saved-jobs/{job_id}': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    /** Save Job */
    put: operations['save_job_api_v1_saved_jobs__job_id__put']
    post?: never
    /** Unsave Job */
    delete: operations['unsave_job_api_v1_saved_jobs__job_id__delete']
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/auth/register': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Register */
    post: operations['register_api_v1_auth_register_post']
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/auth/login': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Login */
    post: operations['login_api_v1_auth_login_post']
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/auth/me': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** Me */
    get: operations['me_api_v1_auth_me_get']
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/auth/logout': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Logout */
    post: operations['logout_api_v1_auth_logout_post']
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/auth/password': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Change Password */
    post: operations['change_password_api_v1_auth_password_post']
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/settings/models': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** Read Models */
    get: operations['read_models_api_v1_settings_models_get']
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/settings/models/{role}': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    /** Write Models */
    put: operations['write_models_api_v1_settings_models__role__put']
    post?: never
    /** Clear Models */
    delete: operations['clear_models_api_v1_settings_models__role__delete']
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/settings/models/{role}/test': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Test Model */
    post: operations['test_model_api_v1_settings_models__role__test_post']
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/settings/usage': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** Read Usage */
    get: operations['read_usage_api_v1_settings_usage_get']
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
}
export type webhooks = Record<string, never>
export interface components {
  schemas: {
    /** AccountResponse */
    AccountResponse: {
      /** User Id */
      user_id: string
      /** Username */
      username: string
      /** Csrf Token */
      csrf_token: string
      /** Expires At */
      expires_at: string
    }
    /**
     * ApplicantError
     * @description User-facing error and next action; internal stages and details stay on the server.
     */
    ApplicantError: {
      /** Code */
      code: string
      /** Message */
      message: string
      /** Action */
      action: ('retry' | 'edit_conditions' | 'reload' | 'start_new_search') | null
    }
    /** ApplicantNotice */
    ApplicantNotice: {
      /**
       * Code
       * @enum {string}
       */
      code:
        | 'source_unavailable'
        | 'source_partial'
        | 'coverage_limited'
        | 'listing_incomplete'
        | 'listing_status_unverified'
        | 'preference_unverified'
        | 'analysis_partial'
        | 'analysis_unavailable'
      /**
       * Scope
       * @enum {string}
       */
      scope: 'session' | 'source' | 'job'
      /** Message */
      message: string
      /** Action */
      action: ('retry' | 'edit_conditions' | 'open_listing') | null
      /** Job Id */
      job_id: string | null
      /** Source */
      source: string | null
      /** Preference */
      preference: string | null
    }
    /** Body_parse_resume_upload_api_v1_resumes_parse_post */
    Body_parse_resume_upload_api_v1_resumes_parse_post: {
      /** File */
      file: string
    }
    /** ClarificationMessage */
    ClarificationMessage: {
      /** Question */
      question: string
      /** Field */
      field: string
      /** Reason */
      reason: string
      /**
       * Required
       * @default true
       */
      required: boolean
      /** @default pending */
      status: components['schemas']['ClarificationStatus']
      /** Answer */
      answer: string | null
      /**
       * Question Id
       * @default
       */
      question_id: string
      /**
       * Control Type
       * @default text
       * @enum {string}
       */
      control_type: 'single_choice' | 'multiple_choice' | 'text'
      /** Options */
      options: components['schemas']['QuestionOption'][]
    }
    /**
     * ClarificationStatus
     * @enum {string}
     */
    ClarificationStatus: 'pending' | 'answered' | 'skipped'
    /** ConnectionResult */
    ConnectionResult: {
      /** Ok */
      ok: boolean
    }
    /** ConversationMessage */
    ConversationMessage: {
      /** Message Id */
      message_id: string
      /**
       * Role
       * @enum {string}
       */
      role: 'user' | 'assistant'
      /** Text */
      text: string
      /** Responses */
      responses: components['schemas']['ConversationResponse'][]
      /** Question Ids */
      question_ids: string[]
      /**
       * Created At
       * Format: date-time
       */
      created_at: string
    }
    /** ConversationResponse */
    ConversationResponse: {
      /** Label */
      label: string
      /** Value */
      value: string | string[]
      /**
       * Status
       * @default answered
       * @enum {string}
       */
      status: 'answered' | 'skipped'
    }
    /** Credentials */
    Credentials: {
      /** Username */
      username: string
      /** Password */
      password: string
    }
    /** DailyUsage */
    DailyUsage: {
      /**
       * Enabled
       * @constant
       */
      enabled: true
      /** Remaining */
      remaining: number
      /** Used */
      used: number
      /** Limit */
      limit: number
      /** Server Remaining */
      server_remaining: number
      /** Day */
      day: string
      /** Timezone */
      timezone: string
    }
    /** DisabledUsage */
    DisabledUsage: {
      /**
       * Enabled
       * @constant
       */
      enabled: false
    }
    /** DraftResponse */
    DraftResponse: {
      /** Data */
      data: {
        [key: string]: unknown
      }
      /** Revision */
      revision: number
      /** Updated At */
      updated_at: string | null
    }
    /** DraftWriteRequest */
    DraftWriteRequest: {
      /** Request Id */
      request_id: string
      /** Expected Revision */
      expected_revision: number
      /** Data */
      data: {
        [key: string]: unknown
      }
    }
    /** EmploymentCondition */
    EmploymentCondition: {
      /** Raw Text */
      raw_text: string | null
      /** Included */
      included: ('full-time' | 'part-time' | 'internship' | 'contract' | 'freelance')[]
      /** Excluded */
      excluded: ('full-time' | 'part-time' | 'internship' | 'contract' | 'freelance')[]
      /**
       * Unrestricted
       * @default false
       */
      unrestricted: boolean
    }
    /**
     * FreshnessStatus
     * @enum {string}
     */
    FreshnessStatus: 'active' | 'expired' | 'unknown'
    /** HTTPValidationError */
    HTTPValidationError: {
      /** Detail */
      detail?: components['schemas']['ValidationError'][]
    }
    /** JobPosting */
    JobPosting: {
      /** Job Id */
      job_id: string
      /** Source */
      source: string
      /** Source Url */
      source_url: string
      /** Title */
      title: string
      /** Company */
      company: string
      /** Location */
      location: string
      /** Salary */
      salary: string | null
      /** Target Direction */
      target_direction: string
      /** Responsibilities */
      responsibilities: string[]
      /** Required Skills */
      required_skills: string[]
      /** Posted At */
      posted_at: string | null
      /** Expiry At */
      expiry_at: string | null
      /** @default unknown */
      freshness_status: components['schemas']['FreshnessStatus']
      /**
       * Fetched At
       * Format: date-time
       */
      fetched_at: string
      /** Source Links */
      source_links: string[]
      /** Source Documents */
      source_documents: components['schemas']['SourceDocument'][]
      /**
       * Description
       * @default
       */
      description: string
      /**
       * Description Is Excerpt
       * @default false
       */
      description_is_excerpt: boolean
      /** Employment Type */
      employment_type: string | null
      /** Target Directions */
      target_directions: string[]
    }
    /** LocationCondition */
    LocationCondition: {
      /** Raw Text */
      raw_text: string | null
      /** Included */
      included: components['schemas']['LocationRef'][]
      /** Excluded */
      excluded: components['schemas']['LocationRef'][]
      /**
       * Unrestricted
       * @default false
       */
      unrestricted: boolean
    }
    /**
     * LocationRef
     * @description A place and its catalog ID, looked up rather than invented by the model.
     */
    LocationRef: {
      /** Id */
      id: string
      /** Name */
      name: string
      /**
       * Region
       * @enum {string}
       */
      region: 'cn' | 'hk'
      /**
       * Level
       * @enum {string}
       */
      level: 'country' | 'region' | 'city' | 'district'
      /** Parent Id */
      parent_id: string | null
      /** Ancestor Ids */
      ancestor_ids: string[]
      /** Source Codes */
      source_codes: {
        [key: string]: string
      }
      /**
       * Resolution
       * @default resolved
       * @enum {string}
       */
      resolution: 'resolved' | 'ambiguous' | 'unsupported'
    }
    /** MatchDimension */
    MatchDimension: {
      /**
       * Id
       * @enum {string}
       */
      id: 'skills' | 'responsibilities' | 'experience' | 'seniority' | 'education' | 'preferences'
      /** Score */
      score: number | null
      /**
       * Status
       * @default unknown
       * @enum {string}
       */
      status: 'assessed' | 'unknown' | 'not_applicable'
      /**
       * Explanation
       * @default
       */
      explanation: string
      /** Requirement Ids */
      requirement_ids: string[]
      /** Profile Fact Ids */
      profile_fact_ids: string[]
      /** Job Source Quotes */
      job_source_quotes: components['schemas']['SourceQuoteReference'][]
      /** Profile Source Quotes */
      profile_source_quotes: components['schemas']['SourceQuoteReference'][]
      /** Missing Information */
      missing_information: string[]
      /** Weight */
      weight: number
      /** Input Hash */
      input_hash: string
    }
    /** MatchScore */
    MatchScore: {
      /** Total */
      total: number | null
      /** Dimensions */
      dimensions: components['schemas']['MatchDimension'][]
      /** Assessed Weight */
      assessed_weight: number
      /** Applicable Weight */
      applicable_weight: number
      /** Assessed Percentage */
      assessed_percentage: number
      /** Provisional */
      provisional: boolean
      /**
       * Completeness
       * @enum {string}
       */
      completeness: 'complete' | 'partial' | 'unknown'
      /** Input Hash */
      input_hash: string
    }
    /** MatchingReason */
    MatchingReason: {
      /** Requirement */
      requirement: string
      /**
       * Level
       * @enum {string}
       */
      level: 'strong' | 'partial' | 'related_experience' | 'not_documented'
      /** Explanation */
      explanation: string
      /** Job Source Quotes */
      job_source_quotes: components['schemas']['SourceQuoteReference'][]
      /** Profile Source Quotes */
      profile_source_quotes: components['schemas']['SourceQuoteReference'][]
    }
    /** ModelEndpoint */
    ModelEndpoint: {
      /** Id */
      id: string
      /** Name */
      name: string
      /** Thinking Supported */
      thinking_supported: boolean
      /** Thinking Level Supported */
      thinking_level_supported: boolean
    }
    /** ModelInfo */
    ModelInfo: {
      /** Personal */
      personal: boolean
      /** Endpoint Id */
      endpoint_id: string | null
      /** Model */
      model: string
      /** Key Configured */
      key_configured: boolean
      /** Server Provider */
      server_provider: string
      /** Server Model */
      server_model: string
      /** Server Key Configured */
      server_key_configured: boolean
      /** Thinking */
      thinking: boolean
      /** Server Thinking */
      server_thinking: boolean
      /** Thinking Level */
      thinking_level: string
      /** Server Thinking Level */
      server_thinking_level: string
    }
    /** ModelRoles */
    ModelRoles: {
      semantic: components['schemas']['ModelInfo']
      decision: components['schemas']['ModelInfo']
    }
    /** ModelSettingsResponse */
    ModelSettingsResponse: {
      roles: components['schemas']['ModelRoles']
      /** Endpoints */
      endpoints: components['schemas']['ModelEndpoint'][]
      /** Personal Available */
      personal_available: boolean
    }
    /** ModelWrite */
    ModelWrite: {
      /** Endpoint Id */
      endpoint_id: string
      /** Model */
      model: string
      /** Api Key */
      api_key?: string | null
      /**
       * Thinking
       * @default false
       */
      thinking?: boolean
      /**
       * Thinking Level
       * @default "high"
       */
      thinking_level?: string
    }
    /** PasswordChange */
    PasswordChange: {
      /** Current Password */
      current_password: string
      /** New Password */
      new_password: string
    }
    /**
     * ProfilePatch
     * @description Only supplied fields change; null clears text and an empty list clears a list.
     */
    ProfilePatch: {
      /** Education */
      education?: string[]
      /** Skills */
      skills?: string[]
      /** Internships */
      internships?: string[]
      /** Projects */
      projects?: string[]
      /** Target Directions */
      target_directions?: string[]
      /** Preferences.Location */
      'preferences.location'?: string | null
      /**
       * Preferences.Location Unrestricted
       * @default false
       */
      'preferences.location_unrestricted'?: boolean
      /** Preferences.Employment Type */
      'preferences.employment_type'?: string | null
      /**
       * Preferences.Employment Type Unrestricted
       * @default false
       */
      'preferences.employment_type_unrestricted'?: boolean
      /** Preferences.Salary Range */
      'preferences.salary_range'?: string | null
      /** Preferences.Work Mode */
      'preferences.work_mode'?: string | null
      /** Preferences.Industry */
      'preferences.industry'?: string | null
    }
    /** ProfilePreferences */
    ProfilePreferences: {
      /** Location */
      location: string | null
      /**
       * Location Unrestricted
       * @default false
       */
      location_unrestricted: boolean
      /** Employment Type */
      employment_type: string | null
      /**
       * Employment Type Unrestricted
       * @default false
       */
      employment_type_unrestricted: boolean
      /** Salary Range */
      salary_range: string | null
      /** Work Mode */
      work_mode: string | null
      /** Industry */
      industry: string | null
      locations: components['schemas']['LocationCondition']
      employment: components['schemas']['EmploymentCondition']
      work_arrangement: components['schemas']['WorkArrangement']
    }
    /** ProfileSource */
    ProfileSource: {
      /**
       * Resume
       * @default false
       */
      resume: boolean
      /**
       * Description
       * @default false
       */
      description: boolean
    }
    /** QuestionAnswer */
    QuestionAnswer: {
      /** Question Id */
      question_id: string
      /** Value */
      value: string | string[]
    }
    /** QuestionOption */
    QuestionOption: {
      /** Id */
      id: string
      /** Label */
      label: string
    }
    /** RawProfilePreferences */
    RawProfilePreferences: {
      /** Location */
      location?: string | null
      /**
       * Location Unrestricted
       * @default false
       */
      location_unrestricted?: boolean
      /** Employment Type */
      employment_type?: string | null
      /**
       * Employment Type Unrestricted
       * @default false
       */
      employment_type_unrestricted?: boolean
      /** Salary Range */
      salary_range?: string | null
      /** Work Mode */
      work_mode?: string | null
      /** Industry */
      industry?: string | null
    }
    /** RecommendationItem */
    RecommendationItem: {
      job: components['schemas']['JobPosting']
      /** Preparation Suggestions */
      preparation_suggestions: string[]
      /** Matching Reasons */
      matching_reasons: components['schemas']['MatchingReason'][]
      /** Notices */
      notices: components['schemas']['ApplicantNotice'][]
      /**
       * Analysis Status
       * @default complete
       * @enum {string}
       */
      analysis_status: 'complete' | 'partial' | 'unavailable'
      /**
       * Review Status
       * @default reviewed
       * @enum {string}
       */
      review_status: 'queued' | 'reviewing' | 'reviewed' | 'not_reviewed'
      /**
       * Verification Status
       * @default unknown
       * @enum {string}
       */
      verification_status: 'confirmed' | 'pending' | 'unknown'
      /** Unknown Conditions */
      unknown_conditions: string[]
      review_issue: components['schemas']['ReviewIssue'] | null
      /**
       * Recommendation Fit
       * @default unknown
       * @enum {string}
       */
      recommendation_fit: 'recommended' | 'possible' | 'unlikely' | 'unknown'
      /**
       * Recommendation Reason
       * @default
       */
      recommendation_reason: string
      match_score: components['schemas']['MatchScore'] | null
    }
    /** RecommendationResult */
    RecommendationResult: {
      /** Session Id */
      session_id: string
      /**
       * Generated At
       * Format: date-time
       */
      generated_at: string
      /** Jobs */
      jobs: components['schemas']['RecommendationItem'][]
      /** Pending Jobs */
      pending_jobs: components['schemas']['RecommendationItem'][]
      /** Notices */
      notices: components['schemas']['ApplicantNotice'][]
      /**
       * Introduction
       * @default
       */
      introduction: string
    }
    /** ResumeInput */
    ResumeInput: {
      /** Name */
      name: string
      /** Text */
      text: string
    }
    /** ReviewIssue */
    ReviewIssue: {
      /**
       * Code
       * @enum {string}
       */
      code:
        | 'timeout'
        | 'service_unavailable'
        | 'invalid_output'
        | 'unverifiable_claims'
        | 'insufficient_job_information'
        | 'incomplete_review'
        | 'failed'
        | 'stopped'
        | 'search_ended'
      /** Stage */
      stage: ('jd_analysis' | 'matching') | null
    }
    /** SaveJobRequest */
    SaveJobRequest: {
      /** Session Id */
      session_id: string
      /** Expected Revision */
      expected_revision: number
    }
    /** SavedJobsResponse */
    SavedJobsResponse: {
      /** Items */
      items: components['schemas']['RecommendationItem'][]
    }
    /** SearchActivity */
    SearchActivity: {
      /** Sequence */
      sequence: number
      /** Job Id */
      job_id: string
      /** Title */
      title: string
      /** Company */
      company: string
      /** Location */
      location: string
      /**
       * Status
       * @enum {string}
       */
      status:
        | 'found'
        | 'queued'
        | 'reviewing'
        | 'reviewed'
        | 'summary_reviewed'
        | 'not_reviewed'
        | 'partial'
        | 'timeout'
        | 'unavailable'
        | 'invalid'
        | 'insufficient'
        | 'failed'
        | 'excluded'
        | 'unverified'
        | 'expired'
        | 'duplicate'
        | 'not_shortlisted'
      review_issue: components['schemas']['ReviewIssue'] | null
      /** Exclusion Reasons */
      exclusion_reasons: ('role' | 'location' | 'employment_type' | 'expired' | 'duplicate')[]
      /** Unknown Conditions */
      unknown_conditions: string[]
      /**
       * Recommendation Fit
       * @default unknown
       * @enum {string}
       */
      recommendation_fit: 'recommended' | 'possible' | 'unlikely' | 'unknown'
    }
    /** SearchEvent */
    SearchEvent: {
      /** Sequence */
      sequence: number
      /** Action */
      action: string
      /** Message */
      message: string
      /** Source */
      source: string | null
    }
    /** SearchOptions */
    'SearchOptions-Input': {
      /**
       * Result Count
       * @default 10
       */
      result_count?: number
    }
    /** SearchOptions */
    'SearchOptions-Output': {
      /**
       * Result Count
       * @default 10
       */
      result_count: number
    }
    /** SearchProgress */
    SearchProgress: {
      /**
       * Sequence
       * @default 0
       */
      sequence: number
      /**
       * Discovered Count
       * @default 0
       */
      discovered_count: number
      /**
       * Analyzed Count
       * @default 0
       */
      analyzed_count: number
      /**
       * Matched Count
       * @default 0
       */
      matched_count: number
      /**
       * Pending Count
       * @default 0
       */
      pending_count: number
      /**
       * Elapsed Seconds
       * @default 0
       */
      elapsed_seconds: number
      /**
       * Retrieval Stopped
       * @default false
       */
      retrieval_stopped: boolean
      /** Events */
      events: components['schemas']['SearchEvent'][]
      /** Activity */
      activity: components['schemas']['SearchActivity'][]
    }
    /** SearchSummary */
    SearchSummary: {
      profile: components['schemas']['UserProfile']
      /** Revision */
      revision: number
      /**
       * Ready
       * @default false
       */
      ready: boolean
      /**
       * Confirmed
       * @default false
       */
      confirmed: boolean
      /** Editable Fields */
      editable_fields: string[]
      /** Missing Fields */
      missing_fields: string[]
      /**
       * Search Limitations
       * @default
       */
      search_limitations: string
    }
    /** SessionCreateRequest */
    SessionCreateRequest: {
      /** Request Id */
      request_id: string
      /**
       * Description
       * @default
       */
      description?: string
      resume?: components['schemas']['ResumeInput'] | null
      /**
       * Resume Consent
       * @default false
       */
      resume_consent?: boolean
      /** Target Directions */
      target_directions?: string[]
      preferences?: components['schemas']['RawProfilePreferences']
      search_options?: components['schemas']['SearchOptions-Input']
    }
    /** SessionHistoryItem */
    SessionHistoryItem: {
      /** Session Id */
      session_id: string
      /** Title */
      title: string
      /** Location */
      location: string
      /**
       * Outcome
       * @enum {string}
       */
      outcome: 'running' | 'paused' | 'completed' | 'failed'
      /** Current Stage */
      current_stage: string
      /** Revision */
      revision: number
      /**
       * Created At
       * Format: date-time
       */
      created_at: string
      /**
       * Updated At
       * Format: date-time
       */
      updated_at: string
      /** Retryable */
      retryable: boolean
      /**
       * Mode
       * @enum {string}
       */
      mode: 'live' | 'replay'
    }
    /** SessionHistoryResponse */
    SessionHistoryResponse: {
      /** Items */
      items: components['schemas']['SessionHistoryItem'][]
      /** Next Cursor */
      next_cursor: string | null
    }
    /** SessionResponse */
    SessionResponse: {
      /** Session Id */
      session_id: string
      /**
       * Outcome
       * @enum {string}
       */
      outcome: 'running' | 'paused' | 'completed' | 'failed'
      /**
       * Current Stage
       * @default ingest
       */
      current_stage: string
      /**
       * Revision
       * @default 0
       */
      revision: number
      profile: components['schemas']['UserProfile'] | null
      /** Clarification Questions */
      clarification_questions: components['schemas']['ClarificationMessage'][]
      /** Conversation */
      conversation: components['schemas']['ConversationMessage'][]
      search_summary: components['schemas']['SearchSummary'] | null
      /** Source Outcomes */
      source_outcomes: components['schemas']['SourceOutcome'][]
      recommendation: components['schemas']['RecommendationResult'] | null
      /** Errors */
      errors: components['schemas']['ApplicantError'][]
      /** Notices */
      notices: components['schemas']['ApplicantNotice'][]
      /**
       * Retryable
       * @default false
       */
      retryable: boolean
      /**
       * Mode
       * @default live
       * @enum {string}
       */
      mode: 'live' | 'replay'
      /** Run Id */
      run_id: string | null
      progress: components['schemas']['SearchProgress']
      /** Stop Reason */
      stop_reason:
        | (
            | 'results_ready'
            | 'target_reached'
            | 'source_exhausted'
            | 'budget_exhausted'
            | 'user_stopped'
            | 'error'
          )
        | null
    }
    /** SessionResumeRequest */
    SessionResumeRequest: {
      /** Request Id */
      request_id: string
      /** Expected Revision */
      expected_revision: number
      /**
       * Message
       * @default
       */
      message?: string
      /** Answers */
      answers?: components['schemas']['QuestionAnswer'][]
      /** Skipped Question Ids */
      skipped_question_ids?: string[]
      /**
       * Action
       * @default answer
       * @enum {string}
       */
      action?: 'answer' | 'confirm_search' | 'edit_conditions' | 'retry'
      profile_updates?: components['schemas']['ProfilePatch']
      search_options?: components['schemas']['SearchOptions-Input'] | null
    }
    /** SessionStopRequest */
    SessionStopRequest: {
      /** Request Id */
      request_id: string
      /** Expected Revision */
      expected_revision: number
      /** Run Id */
      run_id: string
    }
    /** SourceDocument */
    SourceDocument: {
      /** Document Id */
      document_id: string
      /** Source */
      source: string
      /** Source Url */
      source_url: string
      /** Text */
      text: string
      /**
       * Fetched At
       * Format: date-time
       */
      fetched_at: string
      /**
       * Is Excerpt
       * @default false
       */
      is_excerpt: boolean
    }
    /** SourceOutcome */
    SourceOutcome: {
      /**
       * Request Index
       * @default 0
       */
      request_index: number
      /** Target Direction */
      target_direction: string
      /** Source */
      source: string
      /**
       * Candidate Count
       * @default 0
       */
      candidate_count: number
      /**
       * Returned Count
       * @default 0
       */
      returned_count: number
      /**
       * Incomplete Count
       * @default 0
       */
      incomplete_count: number
      /**
       * Excerpt Count
       * @default 0
       */
      excerpt_count: number
      /**
       * Elapsed Seconds
       * @default 0
       */
      elapsed_seconds: number
      /**
       * Status
       * @default ok
       */
      status: string
    }
    /** SourceQuoteReference */
    SourceQuoteReference: {
      /** Document Id */
      document_id: string
      /** Excerpt */
      excerpt: string
      /** Source Url */
      source_url: string | null
    }
    /** UserProfile */
    UserProfile: {
      /** Profile Id */
      profile_id: string
      source: components['schemas']['ProfileSource']
      /** Education */
      education: string[]
      /** Skills */
      skills: string[]
      /** Internships */
      internships: string[]
      /** Projects */
      projects: string[]
      /** Target Directions */
      target_directions: string[]
      preferences: components['schemas']['ProfilePreferences']
      search_options: components['schemas']['SearchOptions-Output']
      /** Confirmed Fields */
      confirmed_fields: string[]
      /** Missing Required Fields */
      missing_required_fields: string[]
      /** Conflicts */
      conflicts: string[]
    }
    /** ValidationError */
    ValidationError: {
      /** Location */
      loc: (string | number)[]
      /** Message */
      msg: string
      /** Error Type */
      type: string
      /** Input */
      input?: unknown
      /** Context */
      ctx?: Record<string, never>
    }
    /** WorkArrangement */
    WorkArrangement: {
      /** Raw Text */
      raw_text: string | null
      /** Included */
      included: ('remote' | 'hybrid' | 'onsite')[]
      /** Excluded */
      excluded: ('remote' | 'hybrid' | 'onsite')[]
      /**
       * Unrestricted
       * @default false
       */
      unrestricted: boolean
      /**
       * Uncertain
       * @default false
       */
      uncertain: boolean
    }
  }
  responses: never
  parameters: never
  requestBodies: never
  headers: never
  pathItems: never
}
export type $defs = Record<string, never>
export interface operations {
  parse_resume_upload_api_v1_resumes_parse_post: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody: {
      content: {
        'multipart/form-data': components['schemas']['Body_parse_resume_upload_api_v1_resumes_parse_post']
      }
    }
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ResumeInput']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  health_check_api_v1_health_get: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': {
            [key: string]: string
          }
        }
      }
    }
  }
  get_history_api_v1_sessions_get: {
    parameters: {
      query?: {
        cursor?: string | null
        limit?: number
      }
      header?: never
      path?: never
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['SessionHistoryResponse']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  create_session_api_v1_sessions_post: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody: {
      content: {
        'application/json': components['schemas']['SessionCreateRequest']
      }
    }
    responses: {
      /** @description Successful Response */
      202: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['SessionResponse']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  get_session_api_v1_sessions__session_id__get: {
    parameters: {
      query?: never
      header?: never
      path: {
        session_id: string
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['SessionResponse']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  delete_session_api_v1_sessions__session_id__delete: {
    parameters: {
      query?: never
      header?: never
      path: {
        session_id: string
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      204: {
        headers: {
          [name: string]: unknown
        }
        content?: never
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  session_events_api_v1_sessions__session_id__events_get: {
    parameters: {
      query?: never
      header?: never
      path: {
        session_id: string
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'text/event-stream': unknown
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  resume_session_api_v1_sessions__session_id__resume_post: {
    parameters: {
      query?: never
      header?: never
      path: {
        session_id: string
      }
      cookie?: never
    }
    requestBody: {
      content: {
        'application/json': components['schemas']['SessionResumeRequest']
      }
    }
    responses: {
      /** @description Successful Response */
      202: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['SessionResponse']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  stop_session_api_v1_sessions__session_id__stop_post: {
    parameters: {
      query?: never
      header?: never
      path: {
        session_id: string
      }
      cookie?: never
    }
    requestBody: {
      content: {
        'application/json': components['schemas']['SessionStopRequest']
      }
    }
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['SessionResponse']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  get_workspace_draft_api_v1_workspace_draft_get: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['DraftResponse']
        }
      }
    }
  }
  save_workspace_draft_api_v1_workspace_draft_put: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody: {
      content: {
        'application/json': components['schemas']['DraftWriteRequest']
      }
    }
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['DraftResponse']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  get_session_draft_api_v1_sessions__session_id__drafts__revision___section__get: {
    parameters: {
      query?: never
      header?: never
      path: {
        session_id: string
        revision: number
        section: 'clarification' | 'summary'
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['DraftResponse']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  save_session_draft_api_v1_sessions__session_id__drafts__revision___section__put: {
    parameters: {
      query?: never
      header?: never
      path: {
        session_id: string
        revision: number
        section: 'clarification' | 'summary'
      }
      cookie?: never
    }
    requestBody: {
      content: {
        'application/json': components['schemas']['DraftWriteRequest']
      }
    }
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['DraftResponse']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  get_saved_jobs_api_v1_saved_jobs_get: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['SavedJobsResponse']
        }
      }
    }
  }
  save_job_api_v1_saved_jobs__job_id__put: {
    parameters: {
      query?: never
      header?: never
      path: {
        job_id: string
      }
      cookie?: never
    }
    requestBody: {
      content: {
        'application/json': components['schemas']['SaveJobRequest']
      }
    }
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['RecommendationItem']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  unsave_job_api_v1_saved_jobs__job_id__delete: {
    parameters: {
      query?: never
      header?: never
      path: {
        job_id: string
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      204: {
        headers: {
          [name: string]: unknown
        }
        content?: never
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  register_api_v1_auth_register_post: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody: {
      content: {
        'application/json': components['schemas']['Credentials']
      }
    }
    responses: {
      /** @description Successful Response */
      201: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['AccountResponse']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  login_api_v1_auth_login_post: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody: {
      content: {
        'application/json': components['schemas']['Credentials']
      }
    }
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['AccountResponse']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  me_api_v1_auth_me_get: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['AccountResponse']
        }
      }
    }
  }
  logout_api_v1_auth_logout_post: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      204: {
        headers: {
          [name: string]: unknown
        }
        content?: never
      }
    }
  }
  change_password_api_v1_auth_password_post: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody: {
      content: {
        'application/json': components['schemas']['PasswordChange']
      }
    }
    responses: {
      /** @description Successful Response */
      204: {
        headers: {
          [name: string]: unknown
        }
        content?: never
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  read_models_api_v1_settings_models_get: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ModelSettingsResponse']
        }
      }
    }
  }
  write_models_api_v1_settings_models__role__put: {
    parameters: {
      query?: never
      header?: never
      path: {
        role: 'semantic' | 'decision'
      }
      cookie?: never
    }
    requestBody: {
      content: {
        'application/json': components['schemas']['ModelWrite']
      }
    }
    responses: {
      /** @description Successful Response */
      204: {
        headers: {
          [name: string]: unknown
        }
        content?: never
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  clear_models_api_v1_settings_models__role__delete: {
    parameters: {
      query?: never
      header?: never
      path: {
        role: 'semantic' | 'decision'
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      204: {
        headers: {
          [name: string]: unknown
        }
        content?: never
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  test_model_api_v1_settings_models__role__test_post: {
    parameters: {
      query?: never
      header?: never
      path: {
        role: 'semantic' | 'decision'
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ConnectionResult']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  read_usage_api_v1_settings_usage_get: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json':
            | components['schemas']['DailyUsage']
            | components['schemas']['DisabledUsage']
        }
      }
    }
  }
}
