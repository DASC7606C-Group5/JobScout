import type { RecommendationItem, ScoutSession, UserProfile } from '../src/lib/contracts'
import type { ProfileFormValues } from '../src/lib/profile-form'
import { summaryFields } from '../src/lib/search-summary'

// Unit-test data only. Application modules must not import this file.
export function createProfileFixture(): ProfileFormValues {
  return {
    description: 'React 开发经历',
    resume: null,
    directions: '前端开发，数据分析',
    preferences: {
      location: '香港',
      location_unrestricted: false,
      employment_type: 'full-time',
      employment_type_unrestricted: false,
      salary_range: 'HK$ 20,000–28,000 / 月',
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
      location: '香港',
      salary: null,
      target_direction: '前端开发',
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
      target_directions: ['前端开发'],
    },
    missing_skills: ['SQL'],
    preparation_suggestions: ['补充项目中的实际使用证据'],
    matching_reasons: [
      {
        requirement: 'React',
        level: 'strong',
        explanation: '项目材料支持 React 经验。',
        job_evidence: [
          {
            document_id: 'job-1',
            excerpt: 'React development experience required.',
            source_url: 'https://example.test/jobs/1',
          },
        ],
        profile_evidence: [
          { document_id: 'description', excerpt: 'React 开发经历', source_url: null },
        ],
      },
      {
        requirement: 'SQL',
        level: 'not_evidenced',
        explanation: '所提供材料未体现 SQL。',
        job_evidence: [],
        profile_evidence: [],
      },
    ],
    uncertainty_notices: ['招聘时效尚未核实。'],
  }
}

export function createUserProfileFixture(): UserProfile {
  return {
    profile_id: 'profile-1',
    source: { description: true, resume: false },
    education: ['合成测试大学'],
    skills: ['React'],
    internships: [],
    projects: ['React 项目'],
    target_directions: ['前端开发'],
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
        text: '请确认以下搜索条件。',
        question_ids: [],
        created_at: '2026-10-03T00:00:00Z',
      },
    ],
    search_summary: {
      profile,
      revision: 1,
      ready: true,
      confirmed: false,
      editable_fields: summaryFields.map(([key]) => key),
      missing_fields: [],
      coverage_notice: '检索香港及中国内地受支持的招聘来源。',
    },
    source_outcomes: [],
    recommendation: null,
    errors: [],
    warnings: [],
    retryable: false,
    mode: 'replay',
    ...overrides,
  }
}
