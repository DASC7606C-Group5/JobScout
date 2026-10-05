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
      <fieldset className="flex flex-wrap gap-2" aria-label="Filter by job direction">
        {directions.map((value) => (
          <button
            key={value}
            className={`btn border shadow-none btn-sm ${direction === value ? 'border-base-content bg-base-content text-base-100' : 'border-base-300 bg-base-100 font-normal text-base-content/65'}`}
            aria-pressed={direction === value}
            onClick={() => onDirectionChange(value)}
          >
            {value}
            {value === 'All' ? ` ${count}` : ''}
          </button>
        ))}
      </fieldset>
      <select
        aria-label="Filter by listing status"
        className="select w-auto border border-base-300 bg-base-100 text-xs select-sm"
        value={freshness}
        onChange={(event) => onFreshnessChange(event.target.value)}
      >
        <option value="all">All statuses</option>
        <option value="active">Active</option>
        <option value="unknown">Status unconfirmed</option>
        <option value="expired">Expired</option>
      </select>
    </div>
  )
}
