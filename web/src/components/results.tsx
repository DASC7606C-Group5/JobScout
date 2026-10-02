import { useState } from 'react'

import type { RecommendationItem, RecommendationResult } from '../lib/contracts'
import { generatedLabel } from '../lib/job-display'
import { Icon } from './icon'
import { JobCard } from './job-card'
import { ResultEmpty } from './results/result-empty'
import { ResultFilters } from './results/result-filters'
import { ResultWarnings } from './results/result-warnings'

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
  const warnings = savedOnly ? [] : (result?.warnings ?? [])
  const filtered = jobs.filter(
    (item) =>
      (selectedDirection === '全部' || item.job.target_direction === selectedDirection) &&
      (freshness === 'all' || item.job.freshness_status === freshness),
  )

  if (!jobs.length) return <ResultEmpty savedOnly={savedOnly} onEdit={onEdit} warnings={warnings} />

  return (
    <section aria-label={savedOnly ? '收藏岗位列表' : '推荐岗位列表'}>
      <ResultWarnings warnings={warnings} />
      <ResultFilters
        directions={directions}
        direction={selectedDirection}
        onDirectionChange={setDirection}
        freshness={freshness}
        onFreshnessChange={setFreshness}
        count={jobs.length}
      />
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
          生成于 {generatedLabel(result.generated_at)} · 香港时间
        </p>
      )}
    </section>
  )
}
