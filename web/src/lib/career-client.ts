import type {
  ApplicationWrite,
  FeedbackWrite,
  JobApplication,
  PersonalProfile,
  ProfileWrite,
  TaskJobFeedback,
} from './career-contracts'

export function createCareerClient(
  base = '/api/v1',
  fetcher: (url: string, init: RequestInit) => Promise<Response> = fetch,
) {
  async function request<T>(path: string, body?: unknown): Promise<T> {
    const response = await fetcher(`${base}${path}`, {
      method: body === undefined ? 'GET' : 'PUT',
      headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    })
    if (!response.ok) throw new Error(`Unable to save or load career records (${response.status}).`)
    return response.json() as Promise<T>
  }
  return {
    renameTask: (sessionId: string, title: string) =>
      request(`/sessions/${encodeURIComponent(sessionId)}/task`, { title }),
    profile: () => request<PersonalProfile>('/profile'),
    saveProfile: (body: ProfileWrite) => request<PersonalProfile>('/profile', body),
    importProfile: (sessionId: string, revision: number) =>
      request<PersonalProfile>('/profile/from-session', {
        session_id: sessionId,
        expected_revision: revision,
      }),
    feedback: (sessionId: string) =>
      request<TaskJobFeedback[]>(`/sessions/${encodeURIComponent(sessionId)}/feedback`),
    saveFeedback: (sessionId: string, jobId: string, body: FeedbackWrite) =>
      request<TaskJobFeedback>(
        `/sessions/${encodeURIComponent(sessionId)}/feedback/${encodeURIComponent(jobId)}`,
        body,
      ),
    applications: () => request<JobApplication[]>('/applications'),
    saveApplication: (jobId: string, body: ApplicationWrite) =>
      request<JobApplication>(`/applications/${encodeURIComponent(jobId)}`, body),
  }
}

export const careerClient = createCareerClient(import.meta.env?.VITE_API_BASE_URL || '/api/v1')
