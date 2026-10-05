import type { ApplicantRecovery } from './contracts'

type ErrorDefinition = { message: string; action: ApplicantRecovery }

const errors = {
  search_unavailable: {
    message: 'Job sources are temporarily unavailable. Try again later.',
    action: 'retry',
  },
  service_unavailable: {
    message:
      'This service is temporarily unavailable. Your information is still here; please try again later.',
    action: 'retry',
  },
  search_timeout: {
    message: 'The search took too long to finish. Try again with your current criteria.',
    action: 'retry',
  },
  analysis_unavailable: {
    message: 'We could not finish reviewing these jobs. Your information is still here.',
    action: 'retry',
  },
  invalid_input: {
    message: 'Check the information you entered and try again.',
    action: 'edit_conditions',
  },
  invalid_answer: {
    message: 'Check your answers or update your search criteria.',
    action: 'edit_conditions',
  },
  search_changed: {
    message: 'Your search has changed. Reload it before continuing.',
    action: 'reload',
  },
  operation_in_progress: {
    message: 'Your search is still being updated. Reload it to see the latest progress.',
    action: 'reload',
  },
  request_conflict: {
    message: 'This change could not be applied. Reload your search before trying again.',
    action: 'reload',
  },
  search_completed: {
    message: 'This search is complete. Edit your criteria to search again.',
    action: 'edit_conditions',
  },
  search_not_found: {
    message: 'This search is no longer available. You can start a new search.',
    action: 'start_new_search',
  },
  search_not_retryable: {
    message: 'Reload your search to see its current progress.',
    action: 'reload',
  },
  connection_unavailable: {
    message: 'Could not connect. Check your connection and try again.',
    action: 'retry',
  },
  invalid_response: {
    message: 'We could not load your search. Please try again.',
    action: 'retry',
  },
  request_failed: {
    message: 'We could not complete this action. Please try again.',
    action: 'retry',
  },
  unsupported_format: {
    message: 'Upload your resume as a PDF, DOCX, or UTF-8 TXT file.',
    action: 'edit_conditions',
  },
  file_too_large: { message: 'Choose a resume under 10 MB.', action: 'edit_conditions' },
  encrypted_file: {
    message: 'Remove the password from this document, then upload it again.',
    action: 'edit_conditions',
  },
  document_too_large: {
    message:
      'This document is too large or complex to read. Shorten it or upload a simpler version.',
    action: 'edit_conditions',
  },
  no_extractable_text: {
    message: 'This file has no readable text. Upload a text-based PDF, DOCX, or TXT version.',
    action: 'edit_conditions',
  },
  empty_file: { message: 'This file is empty. Choose another resume.', action: 'edit_conditions' },
  empty_text: {
    message: 'This file contains no text. Choose another resume.',
    action: 'edit_conditions',
  },
  invalid_encoding: {
    message: 'Save the text file with UTF-8 encoding and upload it again.',
    action: 'edit_conditions',
  },
  invalid_text: {
    message: 'The text could not be read. Re-export the document or upload a UTF-8 TXT file.',
    action: 'edit_conditions',
  },
  text_too_long: {
    message: 'Shorten your resume to 100,000 characters or fewer.',
    action: 'edit_conditions',
  },
  invalid_file: {
    message:
      'This document could not be read. Check that it opens, then re-export it and try again.',
    action: 'edit_conditions',
  },
} satisfies Record<string, ErrorDefinition>

export type ApplicantErrorCode = keyof typeof errors

function knownCode(code: string): code is ApplicantErrorCode {
  return Object.hasOwn(errors, code)
}

export function applicantErrorCode(code: string, status = 0): ApplicantErrorCode {
  if (status >= 500) return 'service_unavailable'
  if (knownCode(code)) return code
  if (status === 404) return 'search_not_found'
  if (status === 409) return 'search_changed'
  if (status === 422) return 'invalid_input'
  if (status === 413) return 'file_too_large'
  if (status === 415) return 'unsupported_format'
  return 'request_failed'
}

export function applicantErrorMessage(code: string, status = 0): string {
  return errors[applicantErrorCode(code, status)].message
}

export function applicantErrorAction(code: string, status = 0): ApplicantRecovery {
  return errors[applicantErrorCode(code, status)].action
}

export function responseErrorCode(body: unknown, status: number): ApplicantErrorCode {
  let code = ''
  if (body && typeof body === 'object' && 'detail' in body) {
    const detail = body.detail
    if (detail && typeof detail === 'object' && 'code' in detail && typeof detail.code === 'string')
      code = detail.code
  }
  return applicantErrorCode(code, status)
}

export class ApplicantRequestError extends Error {
  readonly action: ApplicantRecovery
  constructor(public code: ApplicantErrorCode) {
    super(applicantErrorMessage(code))
    this.name = 'ApplicantRequestError'
    this.action = applicantErrorAction(code)
  }
}
