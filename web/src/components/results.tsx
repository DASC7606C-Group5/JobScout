import { useState } from 'react'

import type { RecommendationItem, RecommendationResult } from '../lib/contracts'
import { Icon } from './icon'
import { JobCard } from './job-card'

export function Results({
  result,
  saved,
  onToggle,
  onEdit,
  savedOnly = false,
}: {
  result: RecommendationResult | null
  saved: RecommendationItem[]
  onToggle: (item: RecommendationItem) => void
  onEdit: () => void
  savedOnly?: boolean
}) {
  const [direction, setDirection] = useState('全部')
  const [freshness, setFreshness] = useState('all')
  const jobs = savedOnly ? saved : (result?.jobs ?? [])
  const directions = ['全部', ...new Set(jobs.map((item) => item.job.target_direction))]
  const selectedDirection = directions.includes(direction) ? direction : '全部'
  const warnings =
    !savedOnly &&
    result?.warnings.map((warning) => (
      <output
        key={warning}
        className="mb-5 flex items-start gap-2.5 rounded-xl border border-accent/70 bg-accent/20 px-4 py-3 text-left text-xs leading-6 text-base-content/70"
      >
        <Icon name="info" size={17} className="mt-1 shrink-0" />
        {warning}
      </output>
    ))
  const filtered = jobs.filter(
    (item) =>
      (selectedDirection === '全部' || item.job.target_direction === selectedDirection) &&
      (freshness === 'all' || item.job.freshness_status === freshness),
  )

  if (!jobs.length)
    return (
      <section className="card items-center border border-base-300 bg-base-100 px-6 py-16 text-center">
        {warnings}
        <span className="mb-5 flex size-16 items-center justify-center rounded-full bg-secondary/35">
          <Icon name={savedOnly ? 'bookmark' : 'search'} size={28} />
        </span>
        <h2 className="text-xl font-semibold">
          {savedOnly ? '把心动的机会留在这里' : '暂时没有找到合适的岗位'}
        </h2>
        <p className="mt-3 max-w-sm text-sm leading-7 text-base-content/60">
          {savedOnly
            ? '点击岗位卡片上的收藏图标，方便稍后比较。收藏仅保留在当前页面，刷新后会清空。'
            : '试着放宽地点限制，或增加一个求职方向，再探索一次。'}
        </p>
        <button className="btn mt-7 rounded-xl border-0 btn-primary" onClick={onEdit}>
          {savedOnly ? '去发现机会' : '调整求职条件'}
          <Icon name="arrow" size={17} />
        </button>
      </section>
    )

  return (
    <section aria-label={savedOnly ? '收藏岗位列表' : '推荐岗位列表'}>
      {warnings}
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <fieldset className="flex flex-wrap gap-2" aria-label="按求职方向筛选">
          {directions.map((value) => (
            <button
              key={value}
              className={`btn rounded-lg border shadow-none btn-sm ${selectedDirection === value ? 'border-base-content bg-base-content text-base-100' : 'border-base-300 bg-base-100 font-normal text-base-content/65'}`}
              aria-pressed={selectedDirection === value}
              onClick={() => setDirection(value)}
            >
              {value}
              {value === '全部' ? ` ${jobs.length}` : ''}
            </button>
          ))}
        </fieldset>
        <select
          aria-label="按岗位时效筛选"
          className="select w-auto rounded-lg border border-base-300 bg-base-100 text-xs select-sm"
          value={freshness}
          onChange={(event) => setFreshness(event.target.value)}
        >
          <option value="all">全部时效</option>
          <option value="active">招聘中</option>
          <option value="unknown">时效待确认</option>
          <option value="expired">已过期</option>
        </select>
      </div>
      <p className="mb-4 text-xs text-base-content/55" aria-live="polite">
        {savedOnly ? '已收藏' : '当前显示'} {filtered.length} 个岗位
        {!savedOnly && ' · 按返回顺序展示'}
      </p>
      {filtered.length ? (
        <div className="grid items-start gap-4 lg:grid-cols-2">
          {filtered.map((item, index) => (
            <JobCard
              key={item.job.job_id}
              item={item}
              index={index}
              saved={saved.some((entry) => entry.job.job_id === item.job.job_id)}
              onToggle={() => onToggle(item)}
            />
          ))}
        </div>
      ) : (
        <div className="rounded-2xl border border-dashed border-base-300 py-12 text-center">
          <p className="text-sm text-base-content/65">没有符合当前筛选条件的岗位。</p>
          <button
            className="btn mt-3 btn-ghost btn-sm"
            onClick={() => {
              setDirection('全部')
              setFreshness('all')
            }}
          >
            清除筛选
          </button>
        </div>
      )}
      {!savedOnly && result && (
        <p className="mt-6 flex items-center gap-1.5 text-xs text-base-content/45">
          <Icon name="clock" size={13} />
          生成于{' '}
          {new Intl.DateTimeFormat('zh-CN', {
            month: 'long',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
            timeZone: 'Asia/Hong_Kong',
          }).format(new Date(result.generated_at))}{' '}
          · 香港时间
        </p>
      )}
    </section>
  )
}
