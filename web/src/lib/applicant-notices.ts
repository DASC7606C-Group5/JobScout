import type { ApplicantNotice } from './contracts'

export function noticeIdentity(notice: ApplicantNotice) {
  return JSON.stringify([
    notice.code,
    notice.scope,
    notice.job_id,
    notice.source,
    notice.preference,
  ])
}

export function uniqueNotices(notices: ApplicantNotice[]) {
  const referenced = [
    ...new Map(notices.map((notice) => [noticeIdentity(notice), notice])).values(),
  ]
  // Two source references may produce the same coverage notice. Show that consequence once.
  return [
    ...new Map(
      referenced.map((notice) => [
        JSON.stringify([
          notice.code,
          notice.scope,
          notice.job_id,
          notice.preference,
          notice.message,
          notice.action,
        ]),
        notice,
      ]),
    ).values(),
  ]
}
