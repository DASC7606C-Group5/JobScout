import { ApplicantRequestError, applicantErrorMessage } from './applicant-errors'
import { SessionHttpError } from './session-client'

export function requestErrorMessage(error: unknown) {
  if (error instanceof SessionHttpError) return applicantErrorMessage(error.code, error.status)
  if (error instanceof ApplicantRequestError) return applicantErrorMessage(error.code)
  return applicantErrorMessage('connection_unavailable')
}
