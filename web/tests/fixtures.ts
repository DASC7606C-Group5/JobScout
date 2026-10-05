import type { RecommendationItem, ScoutSession, UserProfile } from '../src/lib/contracts'
import type { ProfileFormValues } from '../src/lib/profile-form'
import { summaryFields } from '../src/lib/search-summary'

// Unit-test data only. Application modules must not import this file.
export function createProfileFixture(): ProfileFormValues {
  return {
    description: 'React development experience',
    resume: null,
    directions: 'Frontend development, Data analysis',
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
    preparation_suggestions: ['Add evidence of how you used React in a project.'],
    matching_reasons: [
      {
        requirement: 'React',
        level: 'strong',
        explanation: 'Your project materials support your React experience.',
        job_evidence: [
          {
            document_id: 'job-1',
            excerpt: 'React development experience required.',
            source_url: 'https://example.test/jobs/1',
          },
        ],
        profile_evidence: [
          { document_id: 'description', excerpt: 'React development experience', source_url: null },
        ],
      },
      {
        requirement: 'SQL',
        level: 'not_evidenced',
        explanation: 'Your materials do not mention SQL.',
        job_evidence: [],
        profile_evidence: [],
      },
    ],
    notices: [],
    analysis_status: 'complete',
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
    preferences: createProfileFixture().preferences,
    confirmed_fields: [],
    missing_required_fields: [],
    conflicts: [],
  }
}

export function createSessionFixture(overrides: Partial<ScoutSession> = {}): ScoutSession {
  const profile = createUserProfileFixture()
  return {
    session_id: 'session-1',
    outcome: 'paused',
    current_stage: 'confirm',
    revision: 1,
    profile,
    clarification_questions: [],
    conversation: [
      {
        message_id: 'm1',
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
      coverage_notice: 'Search supported job sources in Hong Kong and mainland China.',
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
