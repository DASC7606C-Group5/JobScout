import type { RecommendationItem, ScoutSession, UserProfile } from '../src/lib/contracts'
import { dimensionLabels, type MatchScore } from '../src/lib/matching-contracts'
import type { ProfileFormValues } from '../src/lib/profile-form'
import { summaryFields } from '../src/lib/search-summary'

// Unit-test data only. Application modules must not import this file.
export function createMatchScoreFixture(): MatchScore {
  return {
    total: 80,
    assessed_weight: 30,
    applicable_weight: 95,
    assessed_percentage: 32,
    provisional: true,
    completeness: 'partial',
    input_hash: 'input',
    dimensions: Object.keys(dimensionLabels).map((id, index) => ({
      id: id as keyof typeof dimensionLabels,
      score: index === 0 ? 80 : null,
      status: index === 0 ? 'assessed' : index === 4 ? 'not_applicable' : 'unknown',
      weight: [30, 25, 20, 10, 5, 10][index]!,
      explanation: index === 0 ? 'Built the requested interface' : '',
      requirement_ids: [],
      profile_fact_ids: [],
      job_source_quotes:
        index === 0 ? [{ document_id: 'jd', excerpt: 'Build interfaces', source_url: null }] : [],
      profile_source_quotes:
        index === 0
          ? [{ document_id: 'resume', excerpt: 'Built a React interface', source_url: null }]
          : [],
      missing_information: index === 1 ? ['Daily duties not provided'] : [],
      input_hash: id,
    })),
  }
}

export function createProfileFixture(): ProfileFormValues {
  return {
    description: 'React development experience',
    resume: null,
    resume_consent: false,
    directions: 'Frontend development\nData analysis',
    search_options: { result_count: 10 },
    preferences: {
      location: 'Hong Kong',
      location_unrestricted: false,
      employment_type: 'full-time',
      employment_type_unrestricted: false,
      salary_range: 'HK$20,000–28,000 per month',
      work_mode: null,
      industry: null,
    },
  }
}

export function createRecommendationFixture(): RecommendationItem {
  return {
    job: {
      job_id: 'test-job-1',
      source: 'Test source',
      source_url: 'https://example.test/jobs/1',
      source_links: [],
      title: 'React Engineer',
      company: 'Test Company',
      location: 'Hong Kong',
      salary: null,
      target_direction: 'Frontend development',
      responsibilities: [],
      required_skills: ['React'],
      posted_at: null,
      expiry_at: null,
      fetched_at: '2026-10-03T00:00:00Z',
      freshness_status: 'unknown',
      source_documents: [],
      description: 'React development experience required.',
      description_is_excerpt: false,
      employment_type: 'full-time',
      target_directions: ['Frontend development'],
    },
    preparation_suggestions: ['Describe how you used React in a project.'],
    matching_reasons: [
      {
        requirement: 'React',
        level: 'strong',
        explanation: 'Your project materials support your React experience.',
        job_source_quotes: [
          {
            document_id: 'job-1',
            excerpt: 'React development experience required.',
            source_url: 'https://example.test/jobs/1',
          },
        ],
        profile_source_quotes: [
          { document_id: 'description', excerpt: 'React development experience', source_url: null },
        ],
      },
      {
        requirement: 'SQL',
        level: 'not_documented',
        explanation: 'Your materials do not mention SQL.',
        job_source_quotes: [],
        profile_source_quotes: [],
      },
    ],
    notices: [],
    analysis_status: 'complete',
    review_issue: null,
    match_score: null,
    review_status: 'reviewed',
    recommendation_fit: 'recommended',
    recommendation_reason:
      'The role builds on your React projects; SQL experience is not yet documented.',
    verification_status: 'confirmed',
    unknown_conditions: [],
  }
}

export function createUserProfileFixture(): UserProfile {
  return {
    profile_id: 'profile-1',
    source: { description: true, resume: false },
    education: ['Synthetic Test University'],
    skills: ['React'],
    internships: [],
    projects: ['React project'],
    target_directions: ['Frontend development'],
    preferences: {
      ...createProfileFixture().preferences,
      locations: {
        raw_text: 'Hong Kong',
        included: [
          {
            id: 'hk',
            name: 'Hong Kong',
            region: 'hk',
            level: 'region',
            parent_id: null,
            ancestor_ids: [],
            source_codes: {},
            resolution: 'resolved',
          },
        ],
        excluded: [],
        unrestricted: false,
      },
      employment: {
        raw_text: 'full-time',
        included: ['full-time'],
        excluded: [],
        unrestricted: false,
      },
      work_arrangement: {
        raw_text: null,
        included: [],
        excluded: [],
        unrestricted: false,
        uncertain: false,
      },
    },
    search_options: { result_count: 10 },
    confirmed_fields: [],
    missing_required_fields: [],
    conflicts: [],
  }
}

export function createSessionFixture(overrides: Partial<ScoutSession> = {}): ScoutSession {
  const profile = createUserProfileFixture()
  return {
    session_id: 'session-1',
    operation_kind: 'initial_search',
    job_feedback: [],
    hidden_job_ids: [],
    hidden_job_reasons: [],
    result_preferences: { preferred_features: [], exclusions: [] },
    result_order: [],
    outcome: 'paused',
    current_stage: 'confirm',
    revision: 1,
    run_id: null,
    progress: {
      sequence: 0,
      discovered_count: 0,
      analyzed_count: 0,
      matched_count: 0,
      pending_count: 0,
      elapsed_seconds: 0,
      retrieval_stopped: false,
      events: [],
      activity: [],
    },
    stop_reason: null,
    profile,
    clarification_questions: [],
    conversation: [
      {
        message_id: 'm1',
        job_id: null,
        role: 'assistant',
        text: 'Please confirm the following search criteria.',
        question_ids: [],
        created_at: '2026-10-03T00:00:00Z',
        responses: [],
      },
    ],
    search_summary: {
      profile,
      revision: 1,
      ready: true,
      confirmed: false,
      editable_fields: summaryFields.map(([key]) => key),
      missing_fields: [],
      search_limitations: '',
    },
    source_outcomes: [],
    recommendation: null,
    errors: [],
    notices: [],
    retryable: false,
    mode: 'replay',
    ...overrides,
  }
}
