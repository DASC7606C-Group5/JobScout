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
  // Several job sites may report the same search limitation. Show the message once.
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
