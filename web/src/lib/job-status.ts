import type { RecommendationItem, SearchActivity } from './contracts'
import { hasFullDescription } from './job-display'

export const jobStatuses = [
  'found',
  'queued',
  'reviewing',
  'reviewed',
  'summary_reviewed',
  'not_reviewed',
  'partial',
  'timeout',
  'unavailable',
  'invalid',
  'insufficient',
  'failed',
  'excluded',
  'unverified',
  'expired',
  'duplicate',
  'not_shortlisted',
] as const
export type JobStatus = (typeof jobStatuses)[number]
export const reviewIssueCodes = [
  'timeout',
  'service_unavailable',
  'invalid_output',
  'unverifiable_claims',
  'insufficient_job_information',
  'incomplete_review',
  'failed',
  'stopped',
  'search_ended',
] as const
export interface ReviewIssue {
  code: (typeof reviewIssueCodes)[number]
  stage: 'jd_analysis' | 'matching' | null
}
export const exclusionReasons = [
  'role',
  'location',
  'employment_type',
  'expired',
  'duplicate',
] as const
export type ExclusionReason = (typeof exclusionReasons)[number]

export const statusLabels: Record<JobStatus, string> = {
  found: 'Found',
  queued: 'Waiting',
  reviewing: 'Reviewing',
  reviewed: 'Reviewed',
  summary_reviewed: 'Summary reviewed',
  not_reviewed: 'Not reviewed',
  partial: 'Incomplete',
  timeout: 'Timed out',
  unavailable: 'Review unavailable',
  invalid: 'Review error',
  insufficient: 'Missing details',
  failed: 'Review failed',
  excluded: 'Excluded',
  unverified: 'Needs checking',
  expired: 'Expired',
  duplicate: 'Duplicate',
  not_shortlisted: 'Not shortlisted',
}
const issueLabels: Record<ReviewIssue['code'], string> = {
  timeout: 'The review exceeded its time limit.',
  service_unavailable: 'The review service could not complete the request.',
  invalid_output: 'The review response could not be read or was missing required information.',
  unverifiable_claims:
    'Some conclusions could not be verified against the job listing or your information.',
  insufficient_job_information:
    'The available job information did not provide requirements we could compare with your background.',
  incomplete_review: 'The review did not assess all requirements.',
  failed: 'The review failed; the cause could not be determined.',
  stopped: 'The search was stopped before this review finished.',
  search_ended: 'The search ended before this review finished.',
}
const conditionLabels: Record<string, string> = {
  target_direction: 'Role',
  location: 'Location',
  employment_type: 'Employment type',
}
const exclusionLabels: Record<ExclusionReason, string> = {
  role: 'The role does not match your selected job interests.',
  location: 'The location conflicts with your search criteria.',
  employment_type: 'The employment type conflicts with your search criteria.',
  expired: 'The listing has expired.',
  duplicate: 'This listing duplicates another job.',
}

function issueStatus(issue: ReviewIssue | null): JobStatus {
  switch (issue?.code) {
    case 'timeout':
      return 'timeout'
    case 'service_unavailable':
      return 'unavailable'
    case 'invalid_output':
    case 'unverifiable_claims':
      return 'invalid'
    case 'insufficient_job_information':
      return 'insufficient'
    default:
      return 'failed'
  }
}

export function recommendationStatus(item: RecommendationItem, active: boolean): JobStatus {
  if (item.job.freshness_status === 'expired') return 'expired'
  if (active && (item.review_status === 'queued' || item.review_status === 'reviewing'))
    return item.review_status
  if (item.review_status !== 'reviewed') {
    return item.review_issue && !['stopped', 'search_ended'].includes(item.review_issue.code)
      ? issueStatus(item.review_issue)
      : 'not_reviewed'
  }
  if (item.analysis_status === 'unavailable') return issueStatus(item.review_issue)
  if (item.analysis_status === 'partial')
    return !hasFullDescription(item.job) && !item.review_issue ? 'summary_reviewed' : 'partial'
  if (item.verification_status !== 'confirmed') return 'unverified'
  return 'reviewed'
}

export function statusTooltip(
  status: JobStatus,
  details: Pick<RecommendationItem, 'review_issue' | 'unknown_conditions'> &
    Partial<Pick<SearchActivity, 'exclusion_reasons'>>,
): string {
  if (['found', 'queued', 'reviewing', 'reviewed', 'expired', 'duplicate'].includes(status))
    return ''
  if (status === 'summary_reviewed')
    return 'This advice is based on the listing summary. The full job description was unavailable.'
  if (status === 'not_shortlisted')
    return 'This job ranked outside the requested number of results.'
  if (status === 'excluded')
    return (
      details.exclusion_reasons?.map((reason) => exclusionLabels[reason]).join(' ') ||
      'The job conflicts with a confirmed search condition.'
    )
  const messages: string[] = []
  if (details.review_issue) {
    const stage =
      details.review_issue.stage === 'jd_analysis'
        ? 'Reading job requirements'
        : details.review_issue.stage === 'matching'
          ? 'Comparing your background'
          : null
    messages.push(`${stage ? `${stage}: ` : ''}${issueLabels[details.review_issue.code]}`)
  }
  if (status === 'unverified' || status === 'partial') {
    for (const condition of details.unknown_conditions) {
      messages.push(
        `${conditionLabels[condition] ?? 'Search criterion'} still needs checking against your preferences.`,
      )
    }
  }
  if (messages.length) return messages.join(' ')
  if (status === 'partial') return 'Only part of the review could be completed.'
  if (status === 'unverified')
    return 'Some job details still need checking against your search preferences.'
  if (status === 'not_reviewed') return 'This job has not completed a review.'
  return issueLabels.failed
}

export const fitLabels: Record<RecommendationItem['recommendation_fit'], string> = {
  recommended: 'Recommended',
  possible: 'Worth exploring',
  unlikely: 'Weak match',
  unknown: 'Match unclear',
}
