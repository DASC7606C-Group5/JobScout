import type { ApplicantRecovery } from './contracts'

type ErrorDefinition = { message: string; action: ApplicantRecovery }

const errors = {
  queue_full: {
    message: 'JobScout is busy and can’t accept more requests right now. Try again shortly.',
    action: 'retry',
  },
  queue_expired: {
    message:
      'Your request waited too long to start. Your information is saved. Try again when you’re ready.',
    action: 'retry',
  },
  queue_cancelled: {
    message: 'You cancelled this request before it started. Your information is saved.',
    action: 'retry',
  },
  operation_already_started: {
    message:
      'This request is no longer waiting, so it can’t be cancelled. Refresh to see its progress.',
    action: 'reload',
  },
  event_stream_capacity: {
    message: 'You have too many search tabs open. Close another tab, then try again.',
    action: 'retry',
  },
  upload_capacity: {
    message: 'JobScout is handling other uploads. Please try uploading your resume again shortly.',
    action: 'retry',
  },
  upload_timeout: { message: 'The upload took too long. Try uploading again.', action: 'retry' },
  model_unavailable: {
    message: 'The model request failed. Your input is saved. Check Settings or retry.',
    action: 'retry',
  },
  authentication_required: { message: 'Sign in to continue.', action: 'reload' },
  model_key_required: {
    message: 'Open Settings and configure your models before continuing.',
    action: 'retry',
  },
  operation_capacity: {
    message:
      'You already have a request waiting or running. Wait for it to finish before sending another.',
    action: 'retry',
  },
  server_daily_limit: {
    message:
      'Today’s AI request limit has been reached for your account or for all users. Check Settings, use your own models, or try after midnight (Hong Kong time).',
    action: 'retry',
  },
  search_unavailable: {
    message: 'Job sources are unavailable. Try again later.',
    action: 'retry',
  },
  service_unavailable: {
    message: 'Service unavailable. Try again later.',
    action: 'retry',
  },
  search_timeout: {
    message: 'Search timed out. Try again.',
    action: 'retry',
  },
  analysis_unavailable: {
    message: 'Job review failed. Try again.',
    action: 'retry',
  },
  invalid_input: {
    message: 'Check your information and try again.',
    action: 'edit_conditions',
  },
  resume_consent_required: {
    message: 'Confirm that you consent to sending your resume to the configured AI model.',
    action: 'edit_conditions',
  },
  request_too_large: {
    message: 'The request is too large. Shorten the text or upload a smaller file.',
    action: 'edit_conditions',
  },
  invalid_answer: {
    message: 'Check your answers or search criteria.',
    action: 'edit_conditions',
  },
  search_changed: {
    message: 'Search updated. Reload to continue.',
    action: 'reload',
  },
  draft_conflict: {
    message: 'Draft changed elsewhere. Reload or save your version.',
    action: 'reload',
  },
  search_interrupted: {
    message: 'Search interrupted. Try again.',
    action: 'retry',
  },
  operation_in_progress: {
    message: 'Search is updating. Reload for progress.',
    action: 'reload',
  },
  request_conflict: {
    message: 'Change not applied. Reload and try again.',
    action: 'reload',
  },
  search_completed: {
    message: 'Search complete. Edit criteria to search again.',
    action: 'edit_conditions',
  },
  search_not_found: {
    message: 'Search unavailable. Start a new search.',
    action: 'start_new_search',
  },
  job_not_in_session: {
    message: 'This job is not in the current search. Reload and choose a job again.',
    action: 'reload',
  },
  follow_up_answer_required: {
    message: 'Answer or skip the pending result questions.',
    action: 'reload',
  },
  follow_up_unavailable: {
    message: 'Complete or retry this search before continuing the conversation.',
    action: 'retry',
  },
  invalid_follow_up_input: {
    message: 'Check your result message or answers and try again.',
    action: 'reload',
  },
  search_not_retryable: {
    message: 'Reload to see search progress.',
    action: 'reload',
  },
  connection_unavailable: {
    message: 'Connection failed. Check your connection and retry.',
    action: 'retry',
  },
  invalid_response: {
    message: 'Search could not load. Try again.',
    action: 'retry',
  },
  request_failed: {
    message: 'Action failed. Try again.',
    action: 'retry',
  },
  unsupported_format: {
    message: 'Upload a PDF, DOCX, or UTF-8 TXT resume.',
    action: 'edit_conditions',
  },
  file_too_large: {
    message: 'This file is too large. Compress it or choose a smaller resume.',
    action: 'edit_conditions',
  },
  encrypted_file: {
    message: 'Remove the document password and upload again.',
    action: 'edit_conditions',
  },
  document_too_large: {
    message: 'Document is too large or complex. Upload a shorter or simpler version.',
    action: 'edit_conditions',
  },
  no_extractable_text: {
    message: 'File has no readable text. Upload a text-based PDF, DOCX, or TXT.',
    action: 'edit_conditions',
  },
  empty_file: { message: 'File is empty. Choose another resume.', action: 'edit_conditions' },
  empty_text: {
    message: 'File contains no text. Choose another resume.',
    action: 'edit_conditions',
  },
  invalid_encoding: {
    message: 'Save as UTF-8 TXT and upload again.',
    action: 'edit_conditions',
  },
  invalid_text: {
    message: 'Text could not be read. Re-export or upload a UTF-8 TXT file.',
    action: 'edit_conditions',
  },
  text_too_long: {
    message:
      'Your resume contains too much text. Upload a shorter version with your most relevant experience.',
    action: 'edit_conditions',
  },
  invalid_file: {
    message: 'Document could not be read. Check it opens, then re-export and upload again.',
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
