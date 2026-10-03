import type { RecommendationItem } from '../src/lib/contracts'
import type { ProfileFormValues } from '../src/lib/profile-form'

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
    },
    missing_skills: [],
    preparation_suggestions: [],
  }
}
