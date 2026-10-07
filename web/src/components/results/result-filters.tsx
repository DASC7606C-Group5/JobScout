export function ResultFilters({
  directions,
  direction,
  onDirectionChange,
  freshness,
  onFreshnessChange,
  count,
  filteredCount,
}: {
  directions: string[]
  direction: string
  onDirectionChange: (value: string) => void
  freshness: string
  onFreshnessChange: (value: string) => void
  count: number
  filteredCount: number
}) {
  return (
    <div className="mb-4 flex min-w-0 flex-wrap items-center justify-between gap-2">
      <fieldset
        className="flex max-w-full min-w-0 gap-2 overflow-x-auto py-1"
        aria-label="Filter by type of job"
      >
        {directions.map((value) => (
          <button
            key={value}
            className={`btn shrink-0 border shadow-none btn-sm ${direction === value ? 'border-base-content bg-base-content text-base-100' : 'border-base-300 bg-base-100 font-normal text-base-content/65'}`}
            aria-pressed={direction === value}
            onClick={() => onDirectionChange(value)}
          >
            {value}
          </button>
        ))}
      </fieldset>
      <div className="flex items-center gap-3">
        {(direction !== 'All' || freshness !== 'all') && (
          <output className="text-xs text-base-content/65">
            {filteredCount} of {count} jobs
          </output>
        )}
        <select
          aria-label="Filter by listing status"
          className="select w-auto border border-base-300 bg-base-100 pl-3 text-base select-sm sm:text-xs"
          value={freshness}
          onChange={(event) => onFreshnessChange(event.target.value)}
        >
          <option value="all">All statuses</option>
          <option value="active">Active</option>
          <option value="unknown">Status unconfirmed</option>
          <option value="expired">Expired</option>
        </select>
      </div>
    </div>
  )
}
