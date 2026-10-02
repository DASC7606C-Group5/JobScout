export function ResultFilters({
  directions,
  direction,
  onDirectionChange,
  freshness,
  onFreshnessChange,
  count,
}: {
  directions: string[]
  direction: string
  onDirectionChange: (value: string) => void
  freshness: string
  onFreshnessChange: (value: string) => void
  count: number
}) {
  return (
    <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
      <fieldset className="flex flex-wrap gap-2" aria-label="按求职方向筛选">
        {directions.map((value) => (
          <button
            key={value}
            className={`btn rounded-lg border shadow-none btn-sm ${direction === value ? 'border-base-content bg-base-content text-base-100' : 'border-base-300 bg-base-100 font-normal text-base-content/65'}`}
            aria-pressed={direction === value}
            onClick={() => onDirectionChange(value)}
          >
            {value}
            {value === '全部' ? ` ${count}` : ''}
          </button>
        ))}
      </fieldset>
      <select
        aria-label="按岗位时效筛选"
        className="select w-auto rounded-lg border border-base-300 bg-base-100 text-xs select-sm"
        value={freshness}
        onChange={(event) => onFreshnessChange(event.target.value)}
      >
        <option value="all">全部时效</option>
        <option value="active">招聘中</option>
        <option value="unknown">时效待确认</option>
        <option value="expired">已过期</option>
      </select>
    </div>
  )
}
