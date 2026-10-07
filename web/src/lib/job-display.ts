import type { JobPosting } from './contracts'

export function hasFullDescription(job: JobPosting): boolean {
  return (
    Boolean(job.description.trim() && !job.description_is_excerpt) ||
    job.source_documents.some(
      (document) =>
        document.text.trim() && !document.is_excerpt && !document.document_id.endsWith(':metadata'),
    )
  )
}

const dateFormatter = new Intl.DateTimeFormat('en-HK', {
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  timeZone: 'Asia/Hong_Kong',
})
const generatedFormatter = new Intl.DateTimeFormat('en-HK', {
  month: 'long',
  day: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  timeZone: 'Asia/Hong_Kong',
})
const sourceNames: Record<string, string> = {
  jobsdb: 'JobsDB',
  liepin: 'Liepin',
  zhaopin: 'Zhaopin',
  shixiseng: 'Shixiseng',
  remotive: 'Remotive',
  arbeitnow: 'Arbeitnow',
  careerjet: 'Careerjet',
  careerjet_hk: 'Careerjet',
  careerjet_cn: 'Careerjet',
}

export function sourceLabel(source: string) {
  return sourceNames[source] ?? 'Job source'
}

export function generatedLabel(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? 'Not provided' : generatedFormatter.format(date)
}
export function dateLabel(value: string | null) {
  if (!value) return 'Not provided'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? 'Not provided' : dateFormatter.format(date)
}

export function safeSourceUrl(value: string): string | null {
  try {
    const url = new URL(value)
    return ['https:', 'http:'].includes(url.protocol) ? url.href : null
  } catch {
    return null
  }
}
