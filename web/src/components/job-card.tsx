import type { RecommendationItem } from '../lib/contracts'
import { Icon } from './icon'

const statusLabels = {
  active: { label: '招聘中', style: 'bg-primary/20 text-primary-content' },
  unknown: { label: '时效待确认', style: 'bg-accent/40 text-accent-content' },
  expired: { label: '已过期', style: 'bg-base-200 text-base-content/65' },
}

function dateLabel(value: string | null) {
  if (!value) return '未提供'
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? '未提供'
    : new Intl.DateTimeFormat('zh-CN', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        timeZone: 'Asia/Hong_Kong',
      }).format(date)
}

export function safeSourceUrl(value: string): string | null {
  try {
    const url = new URL(value)
    return ['https:', 'http:'].includes(url.protocol) ? url.href : null
  } catch {
    return null
  }
}

export function JobCard({
  item,
  index,
  saved,
  onToggle,
}: {
  item: RecommendationItem
  index: number
  saved: boolean
  onToggle: () => void
}) {
  const { job } = item
  const status = statusLabels[job.freshness_status]
  const links = [...new Set([job.source_url, ...job.source_links])].flatMap((value) => {
    const href = safeSourceUrl(value)
    return href ? [href] : []
  })
  return (
    <article className="card border border-base-300 bg-base-100 transition-shadow hover:shadow-md">
      <div className="p-5 sm:p-6">
        <div className="flex items-start gap-3.5">
          <div
            className={`flex size-12 shrink-0 items-center justify-center rounded-2xl text-lg font-semibold ${['bg-primary/20 text-primary-content', 'bg-secondary/50 text-secondary-content', 'bg-accent/45 text-accent-content'][index % 3]}`}
          >
            {job.company.slice(0, 1)}
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-xs text-base-content/55">{job.company}</p>
            <h3 className="mt-1 text-lg font-semibold tracking-tight">{job.title}</h3>
          </div>
          <button
            className={`btn btn-square shrink-0 btn-ghost btn-sm ${saved ? 'text-secondary-content' : 'text-base-content/50'}`}
            aria-label={`${saved ? '取消收藏' : '收藏'}${job.title}`}
            aria-pressed={saved}
            onClick={onToggle}
          >
            <Icon name="bookmark" className={saved ? 'fill-secondary' : ''} />
          </button>
        </div>
        <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-base-content/65">
          <span className="inline-flex items-center gap-1.5">
            <Icon name="pin" size={14} />
            {job.location}
          </span>
          <span className="inline-flex items-center gap-1.5">
            <Icon name="briefcase" size={14} />
            {job.target_direction}
          </span>
          <span className={`badge border-0 badge-sm ${status.style}`}>{status.label}</span>
        </div>
        <p className="mt-4 text-sm font-semibold">{job.salary || '薪资未提供'}</p>
        <div className="mt-3 flex flex-wrap gap-1.5">
          {job.required_skills.map((skill) => (
            <span
              className="badge border-0 bg-base-200/65 px-2.5 text-xs badge-sm font-normal text-base-content/70"
              key={skill}
            >
              {skill}
            </span>
          ))}
        </div>
        <details className="group mt-5 border-t border-base-300 pt-4">
          <summary className="flex cursor-pointer list-none items-center justify-between rounded text-xs font-medium">
            岗位详情与准备建议
            <Icon name="chevron" size={16} className="transition-transform group-open:rotate-90" />
          </summary>
          <div className="mt-5 space-y-5 text-sm leading-6">
            <section>
              <h4 className="mb-2 font-semibold">你将参与</h4>
              {job.responsibilities.length ? (
                <ul className="list-disc space-y-1 pl-4 text-base-content/70">
                  {job.responsibilities.map((responsibility) => (
                    <li key={responsibility}>{responsibility}</li>
                  ))}
                </ul>
              ) : (
                <p className="text-base-content/60">暂未提供职责说明。</p>
              )}
            </section>
            <section className="rounded-xl bg-secondary/25 p-4">
              <h4 className="mb-2 flex items-center gap-2 font-semibold">
                <Icon name="sparkles" size={16} />
                可以提前准备
              </h4>
              <p className="text-xs text-base-content/65">
                {item.missing_skills.length
                  ? `待补技能：${item.missing_skills.join('、')}`
                  : '暂未列出待补技能。'}
              </p>
              {item.preparation_suggestions.length ? (
                <ul className="mt-2 list-disc space-y-1 pl-4 text-base-content/75">
                  {item.preparation_suggestions.map((suggestion) => (
                    <li key={suggestion}>{suggestion}</li>
                  ))}
                </ul>
              ) : (
                <p className="mt-2 text-base-content/65">暂未提供准备建议。</p>
              )}
            </section>
            <dl className="grid grid-cols-2 gap-3 text-xs">
              <div>
                <dt className="text-base-content/50">信息来源</dt>
                <dd className="mt-1">{job.source}</dd>
              </div>
              <div>
                <dt className="text-base-content/50">获取时间</dt>
                <dd className="mt-1">{dateLabel(job.fetched_at)}</dd>
              </div>
              <div>
                <dt className="text-base-content/50">发布时间</dt>
                <dd className="mt-1">{dateLabel(job.posted_at)}</dd>
              </div>
              <div>
                <dt className="text-base-content/50">截止时间</dt>
                <dd className="mt-1">{dateLabel(job.expiry_at)}</dd>
              </div>
            </dl>
            {job.freshness_status === 'unknown' && (
              <p className="rounded-lg bg-accent/30 p-3 text-xs text-accent-content">
                尚未确认是否仍在招聘，请以来源页面为准。
              </p>
            )}
            {job.freshness_status === 'expired' && (
              <p className="text-xs text-base-content/60">该岗位已过期，保留供参考。</p>
            )}
            <div className="flex flex-wrap gap-3">
              {links.map((href, linkIndex) => (
                <a
                  key={href}
                  href={href}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1.5 text-xs text-primary-content underline-offset-4 hover:underline"
                >
                  {linkIndex ? `其他来源 ${linkIndex}` : '查看来源'}
                  {new URL(href).hostname === 'example.com' ? '（示例）' : ''}
                  <Icon name="external" size={12} />
                </a>
              ))}
            </div>
          </div>
        </details>
      </div>
    </article>
  )
}
