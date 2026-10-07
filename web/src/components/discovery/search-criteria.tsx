import type { UserProfile } from '../../lib/contracts'
import { Icon } from '../icon'

export function SearchCriteria({
  profile,
  canEdit,
  onEdit,
}: {
  profile: UserProfile
  canEdit: boolean
  onEdit: () => void
}) {
  const directions = profile.target_directions
  const conditions = [
    {
      id: 'location',
      value: profile.preferences.location_unrestricted
        ? 'Any location'
        : profile.preferences.location,
    },
    {
      id: 'employment',
      value: profile.preferences.employment_type_unrestricted
        ? 'Any employment type'
        : profile.preferences.employment_type,
    },
    { id: 'count', value: `Up to ${profile.search_options.result_count} jobs` },
  ].filter(({ value }) => Boolean(value))

  return (
    <section
      className="relative mb-6 min-w-0 rounded-box border border-primary-content/15 bg-primary/15"
      aria-label="Search criteria"
    >
      <details className="group collapse">
        <summary className="collapse-title flex min-h-14 items-center gap-2 py-3 pr-36 pl-4 text-primary-content sm:pl-5">
          <Icon
            name="chevron"
            size={16}
            className="shrink-0 transition-transform group-open:rotate-90"
          />
          <h2 className="text-sm font-semibold">Search criteria</h2>
        </summary>
        <div className="collapse-content px-4 sm:px-5">
          {directions.length > 0 && (
            <div className="mt-3 flex min-w-0 items-center gap-2">
              <div className="flex min-w-0 items-center gap-2">
                {directions.slice(0, 2).map((direction, index) => (
                  <span
                    key={`${index}-${direction}`}
                    className={`badge h-8 max-w-64 min-w-0 border-primary-content/15 bg-base-100 px-3 font-normal text-base-content ${index === 1 ? 'hidden sm:inline-flex' : ''}`}
                  >
                    <span className="truncate">{direction}</span>
                  </span>
                ))}
              </div>
              {directions.length > 1 && (
                <span className="badge h-8 shrink-0 border-primary-content/15 bg-base-100 px-3 font-normal text-primary-content sm:hidden">
                  +{directions.length - 1} more…
                </span>
              )}
              {directions.length > 2 && (
                <span className="badge hidden h-8 shrink-0 border-primary-content/15 bg-base-100 px-3 font-normal text-primary-content sm:inline-flex">
                  +{directions.length - 2} more…
                </span>
              )}
            </div>
          )}
          <ul
            className="mt-3 flex flex-wrap gap-x-3 gap-y-1 text-sm leading-6 text-base-content/85"
            aria-label="Location, employment type and job count"
          >
            {conditions.map((condition, index) => (
              <li key={condition.id} className="flex min-w-0 items-start gap-3">
                {index > 0 && (
                  <span aria-hidden="true" className="text-base-content/40">
                    ·
                  </span>
                )}
                <span className="wrap-anywhere">{condition.value}</span>
              </li>
            ))}
          </ul>
        </div>
      </details>
      <button
        type="button"
        className="btn absolute top-3 right-3 btn-ghost text-primary-content btn-sm sm:right-4"
        disabled={!canEdit}
        onClick={onEdit}
      >
        <Icon name="compass" size={15} />
        Edit criteria
      </button>
    </section>
  )
}
