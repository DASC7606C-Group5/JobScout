import type { UserProfile } from '../../lib/contracts'
import { summaryDraft, summaryFields } from '../../lib/search-summary'
import { Icon } from '../icon'
import { SummaryValues } from '../profile/profile-summary'

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
  const location = profile.preferences.location_unrestricted
    ? 'Any location'
    : profile.preferences.location || 'Location not provided'
  return (
    <section
      className="search-criteria relative mb-4 min-w-0 rounded-box bg-primary/10"
      aria-label="Search criteria"
    >
      <details className="group collapse rounded-none">
        <summary className="collapse-title flex min-h-0 items-center gap-2 py-3 pr-28 pl-4 text-sm">
          <Icon
            name="chevron"
            size={15}
            className="shrink-0 transition-transform group-open:rotate-90"
          />
          <span className="min-w-0">
            <span className="block truncate font-medium">
              {directions[0] || 'Search criteria'}
              {directions.length > 1 ? ` +${directions.length - 1}` : ''}
            </span>
            <span className="block truncate text-xs text-base-content/65">{location}</span>
          </span>
        </summary>
        <div className="collapse-content px-4 pt-3">
          <SummaryValues
            fields={summaryFields.filter(
              ([key]) =>
                key === 'target_directions' ||
                key.startsWith('preferences.') ||
                key === 'search_options.result_count',
            )}
            draft={summaryDraft(profile)}
            profile={profile}
          />
        </div>
      </details>
      <button
        type="button"
        className="btn absolute top-3 right-2 btn-ghost text-primary-content btn-sm"
        disabled={!canEdit}
        onClick={onEdit}
      >
        Edit criteria
      </button>
    </section>
  )
}
