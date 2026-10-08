import type { ApplicantRecovery } from './contracts'

type ErrorDefinition = { message: string; action: ApplicantRecovery }

const errors = {
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
    message: 'Another operation is running. Try again after it finishes.',
    action: 'retry',
  },
  server_daily_limit: {
    message:
      'The server model daily allowance has been used. Configure personal models in Settings or try tomorrow.',
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
  file_too_large: { message: 'Choose a resume under 10 MB.', action: 'edit_conditions' },
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
    message: 'Shorten your resume to 100,000 characters or fewer.',
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
