import type { UserProfile } from '../../lib/contracts'
import { summaryDraft, summaryFields, type SummaryDraft } from '../../lib/search-summary'

export function SummaryValues({
  fields,
  draft,
  profile,
  collapseLongValues = true,
}: {
  fields: (typeof summaryFields)[number][]
  draft: SummaryDraft
  profile?: UserProfile | undefined
  collapseLongValues?: boolean
}) {
  const visible = fields.filter(
    ([key, , kind]) =>
      kind !== 'boolean' &&
      (key === 'target_directions' ||
        key === 'preferences.location' ||
        key === 'preferences.employment_type' ||
        String(draft[key]).trim()),
  )
  if (!visible.length) return <p className="text-sm text-base-content/65">No details provided.</p>
  return (
    <dl className="grid min-w-0 gap-x-6 gap-y-3 text-sm sm:grid-cols-2">
      {visible.map(([key, label, kind]) => {
        let value = String(draft[key])
        let excluded = ''
        if (key === 'preferences.location') {
          const same =
            draft[key] === (profile?.preferences.location ?? '') &&
            draft['preferences.location_unrestricted'] ===
              profile?.preferences.location_unrestricted
          const locations = same ? profile?.preferences.locations : undefined
          value = draft['preferences.location_unrestricted']
            ? 'Any location'
            : locations?.included.length
              ? locations.included
                  .map(
                    (place) =>
                      `${place.name}${place.resolution === 'resolved' ? '' : ' (needs clarification)'}`,
                  )
                  .join(', ')
              : value
          excluded = locations?.excluded.map((place) => place.name).join(', ') ?? ''
        }
        if (key === 'preferences.employment_type') {
          const same =
            draft[key] === (profile?.preferences.employment_type ?? '') &&
            draft['preferences.employment_type_unrestricted'] ===
              profile?.preferences.employment_type_unrestricted
          const employment = same ? profile?.preferences.employment : undefined
          value = draft['preferences.employment_type_unrestricted']
            ? 'Any employment type'
            : employment?.included.length
              ? employment.included.join(', ')
              : value
          excluded = employment?.excluded.join(', ') ?? ''
        }
        if (key === 'preferences.work_mode')
          value =
            (
              {
                onsite: 'On-site',
                hybrid: 'Hybrid',
                remote: 'Remote',
                unrestricted: 'No preference',
              } as Record<string, string>
            )[value] ?? value
        if (kind === 'number') value = `Up to ${value} jobs`
        const lines = value.split('\n')
        return (
          <div key={key} className="grid min-w-0 grid-cols-[6.5rem_minmax(0,1fr)] gap-x-3 sm:block">
            <dt className="text-xs text-base-content/65">{label}</dt>
            <dd className="wrap-anywhere whitespace-pre-wrap sm:mt-1">
              {collapseLongValues && lines.length > 2 ? (
                <>
                  {lines.slice(0, 2).join('\n')}
                  <details className="mt-1">
                    <summary className="flex min-h-8 items-center text-xs text-primary-content">
                      Show all {label.toLowerCase()}
                    </summary>
                    <div className="mt-2">{lines.slice(2).join('\n')}</div>
                  </details>
                </>
              ) : value.trim() ? (
                value
              ) : (
                <span className="text-base-content/55">Not provided</span>
              )}
              {excluded && <p className="mt-1">Excluded: {excluded}</p>}
            </dd>
          </div>
        )
      })}
    </dl>
  )
}

export function ProfileSummary({ profile }: { profile: UserProfile }) {
  return (
    <details className="collapse-arrow collapse border border-base-300 bg-base-100">
      <summary className="collapse-title text-sm font-medium">Your information so far</summary>
      <div className="collapse-content">
        <SummaryValues
          fields={[...summaryFields]}
          draft={summaryDraft(profile)}
          profile={profile}
        />
      </div>
    </details>
  )
}
