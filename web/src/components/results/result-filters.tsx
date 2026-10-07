import { useId, type CSSProperties } from 'react'

import type { RecommendationItem } from '../../lib/contracts'
import { employmentLabel } from '../../lib/job-display'
import { fitLabels } from '../../lib/job-status'
import {
  freshnessLabels,
  sortLabels,
  visibleJobs,
  type ResultSearch,
} from '../../lib/result-navigation'
import { Icon } from '../icon'

type FilterProps = {
  jobs: RecommendationItem[]
  search: ResultSearch
  onChange: (value: ResultSearch) => void
}

export function ResultFilters({
  jobs,
  directions,
  search,
  onChange,
  filteredCount,
}: FilterProps & { directions: string[]; filteredCount: number }) {
  const id = useId().replace(/[^a-zA-Z0-9-]/g, '')
  const panelId = `job-filters-${id}`
  const anchorName = `--${panelId}`
  const activeFilterCount = [search.freshness, search.fit, search.employment].filter(Boolean).length
  const hasFilters = Boolean(search.direction || activeFilterCount)
  return (
    <fieldset
      aria-label="Job filters and sorting"
      className="mb-4 flex min-w-0 shrink-0 items-center gap-2 sm:gap-3"
    >
      <div className="flex min-w-0 flex-1 items-center gap-2 overflow-x-auto py-1.5">
        <DirectionFilters jobs={jobs} directions={directions} search={search} onChange={onChange} />
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <output
          aria-live="polite"
          className="sr-only shrink-0 text-xs text-base-content/60 tabular-nums xl:not-sr-only"
        >
          <span className="font-semibold text-base-content">{filteredCount}</span>
          {hasFilters ? ` of ${jobs.length} jobs` : ` ${jobs.length === 1 ? 'job' : 'jobs'}`}
        </output>
        {hasFilters && (
          <button
            type="button"
            aria-label="Clear filters"
            className="btn h-9 gap-1.5 btn-ghost px-2 text-base-content/65 btn-sm"
            onClick={() => onChange({ sort: search.sort })}
          >
            <Icon name="close" size={14} />
            <span className="hidden xl:inline">Clear filters</span>
          </button>
        )}
        <button
          type="button"
          popoverTarget={panelId}
          style={{ anchorName } as CSSProperties}
          className={`btn h-9 gap-1.5 px-2.5 shadow-none btn-sm ${activeFilterCount ? 'border-base-content/20 bg-secondary/25' : 'border-base-300 bg-base-100'}`}
        >
          <Icon name="settings" size={16} />
          <span className="sr-only sm:not-sr-only">Filters</span>
          {activeFilterCount > 0 && (
            <span className="badge border-0 bg-base-content badge-sm text-base-100">
              {activeFilterCount}
            </span>
          )}
        </button>
        <label className="relative min-w-0">
          <Icon
            name="sort"
            size={16}
            className="pointer-events-none absolute top-2.5 left-3 z-1 text-base-content/60"
          />
          <select
            aria-label="Sort jobs"
            className="select h-9 w-40 border-base-300 bg-base-100 px-9! text-center font-medium shadow-none select-sm [text-align-last:center] sm:w-48"
            value={search.sort ?? 'recommended'}
            onChange={(event) =>
              onChange({
                ...search,
                sort:
                  event.target.value === 'recommended'
                    ? undefined
                    : (event.target.value as ResultSearch['sort']),
              })
            }
          >
            {Object.entries(sortLabels).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
      </div>
      <FilterPanel
        id={panelId}
        anchorName={anchorName}
        jobs={jobs}
        search={search}
        onChange={onChange}
      />
    </fieldset>
  )
}

function DirectionFilters({
  jobs,
  directions,
  search,
  onChange,
}: FilterProps & { directions: string[] }) {
  const available = visibleJobs(jobs, { ...search, direction: undefined, sort: undefined })
  return (
    <fieldset className="flex shrink-0 gap-1.5" aria-label="Filter by type of job">
      {directions.map((value) => {
        const direction = value === 'All' ? undefined : value
        const selected = search.direction === direction
        const count = visibleJobs(available, { direction }).length
        return (
          <button
            key={value}
            type="button"
            aria-label={value === 'All' ? 'All jobs' : value}
            aria-pressed={selected}
            title={value}
            className={`btn h-8 shrink-0 gap-2 border shadow-none btn-sm ${selected ? 'border-base-content bg-base-content text-base-100' : 'border-transparent bg-transparent font-normal text-base-content/65 hover:border-base-300 hover:bg-base-200'}`}
            onClick={() => onChange({ ...search, direction })}
          >
            <span className="max-w-52 truncate">{value === 'All' ? 'All jobs' : value}</span>
            <span className={`text-xs tabular-nums ${selected ? 'opacity-65' : 'opacity-60'}`}>
              {count}
            </span>
          </button>
        )
      })}
    </fieldset>
  )
}

function FilterPanel({
  id,
  anchorName,
  jobs,
  search,
  onChange,
}: FilterProps & { id: string; anchorName: string }) {
  const employmentTypes = [...new Set(jobs.flatMap(({ job }) => job.employment_type || []))].sort()
  const fields = [
    {
      key: 'freshness',
      label: 'Hiring status',
      ariaLabel: 'Filter by hiring status',
      all: 'All jobs',
      options: freshnessLabels,
    },
    {
      key: 'fit',
      label: 'Match result',
      ariaLabel: 'Filter by match result',
      all: 'All match results',
      options: fitLabels,
    },
    {
      key: 'employment',
      label: 'Employment type',
      ariaLabel: 'Filter by employment type',
      all: 'All employment types',
      options: Object.fromEntries(employmentTypes.map((value) => [value, employmentLabel(value)])),
    },
  ] as const
  return (
    <div
      id={id}
      popover="auto"
      aria-label="Job filters"
      className="dropdown dropdown-center mt-2 w-80 max-w-[calc(100vw-2rem)] rounded-box border border-base-300 bg-base-100 p-4 text-base-content shadow-lg sm:dropdown-end"
      style={{ positionAnchor: anchorName } as CSSProperties}
    >
      <div className="mb-4 flex items-center justify-between gap-3">
        <h3 className="text-sm font-semibold">Filter jobs</h3>
        <button
          type="button"
          aria-label="Close filters"
          popoverTarget={id}
          popoverTargetAction="hide"
          className="btn btn-circle btn-ghost text-base-content/60 btn-xs"
        >
          <Icon name="close" size={15} />
        </button>
      </div>
      <div className="space-y-4">
        {fields.map(({ key, label, ariaLabel, all, options }) => (
          <label key={key} className="block space-y-1.5">
            <span className="block text-xs font-medium text-base-content/65">{label}</span>
            <select
              aria-label={ariaLabel}
              className="select w-full border-base-300 bg-base-100 select-sm"
              value={search[key] ?? ''}
              onChange={(event) => onChange({ ...search, [key]: event.target.value || undefined })}
            >
              <option value="">{all}</option>
              {Object.entries(options).map(([value, optionLabel]) => (
                <option key={value} value={value}>
                  {optionLabel}
                </option>
              ))}
            </select>
          </label>
        ))}
      </div>
    </div>
  )
}
