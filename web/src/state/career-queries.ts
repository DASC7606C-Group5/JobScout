import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { careerClient } from '../lib/career-client'
import type { ApplicationWrite, FeedbackWrite, ProfileWrite } from '../lib/career-contracts'

export const profileKey = ['career', 'profile'] as const
export const applicationsKey = ['career', 'applications'] as const
export const feedbackKey = (id: string) => ['career', 'feedback', id] as const
export const useCurrentProfile = () =>
  useQuery({ queryKey: profileKey, queryFn: () => careerClient.profile() })
export const useApplications = () =>
  useQuery({ queryKey: applicationsKey, queryFn: () => careerClient.applications() })
export const useTaskFeedback = (id?: string) =>
  useQuery({
    queryKey: feedbackKey(id ?? ''),
    queryFn: () => careerClient.feedback(id!),
    enabled: Boolean(id),
  })

export function useSaveProfile() {
  const cache = useQueryClient()
  return useMutation({
    mutationFn: (body: ProfileWrite) => careerClient.saveProfile(body),
    onSuccess: (value) => cache.setQueryData(profileKey, value),
  })
}
export function useSaveFeedback(sessionId: string, jobId: string) {
  const cache = useQueryClient()
  return useMutation({
    mutationFn: (body: FeedbackWrite) => careerClient.saveFeedback(sessionId, jobId, body),
    onSuccess: () => cache.invalidateQueries({ queryKey: feedbackKey(sessionId) }),
  })
}
export function useSaveApplication(jobId: string) {
  const cache = useQueryClient()
  return useMutation({
    mutationFn: (body: ApplicationWrite) => careerClient.saveApplication(jobId, body),
    onSuccess: () => cache.invalidateQueries({ queryKey: applicationsKey }),
  })
}
