import type { ProfilePreferences } from '../../lib/contracts'

export function InterpretedConditions({ preferences }: { preferences: ProfilePreferences }) {
  const { locations, employment } = preferences
  const complex =
    locations.included.length > 1 ||
    locations.excluded.length > 0 ||
    employment.included.length > 1 ||
    employment.excluded.length > 0 ||
    locations.included.some((place) => place.resolution !== 'resolved')
  const places = (items: typeof locations.included) =>
    items
      .map(
        (place) =>
          `${place.name}${place.resolution === 'resolved' ? '' : ' (needs clarification)'}`,
      )
      .join(', ')
  return (
    <details
      className="collapse-arrow collapse border border-base-300 bg-base-200/25 text-sm"
      open={complex}
    >
      <summary className="collapse-title font-medium">
        How your preferences will be searched
      </summary>
      <dl className="collapse-content grid gap-3 sm:grid-cols-2">
        <div>
          <dt className="text-xs text-base-content/60">Locations</dt>
          <dd className="mt-1 break-words">
            {locations.unrestricted
              ? 'Any supported location'
              : places(locations.included) || 'Choose a location above'}
          </dd>
          {locations.excluded.length > 0 && (
            <dd className="mt-1">Excluded: {places(locations.excluded)}</dd>
          )}
        </div>
        <div>
          <dt className="text-xs text-base-content/60">Employment</dt>
          <dd className="mt-1 break-words">
            {employment.unrestricted
              ? 'Any employment type'
              : employment.included.join(', ') || 'Choose an employment type above'}
          </dd>
          {employment.excluded.length > 0 && (
            <dd className="mt-1">Excluded: {employment.excluded.join(', ')}</dd>
          )}
        </div>
      </dl>
    </details>
  )
}
