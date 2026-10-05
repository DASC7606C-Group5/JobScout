import type { SearchSummary as Summary } from '../lib/contracts'
import { profileFieldLabel } from '../lib/conversation'
import {
  summaryDirectionError,
  summaryDraft,
  summaryFields,
  summaryUpdates,
  type SummaryDraft,
  type SummaryKey,
} from '../lib/search-summary'
import { useScoutSession } from '../state/session-context'
import { useSessionDraft } from '../state/use-session-draft'

const employmentOptions = [
  ['full-time', 'Full-time'],
  ['internship', 'Internship'],
  ['part-time', 'Part-time'],
  ['contract', 'Contract'],
  ['freelance', 'Freelance'],
] as const
const workModeOptions = [
  ['onsite', 'On-site'],
  ['hybrid', 'Hybrid'],
  ['remote', 'Remote'],
] as const

function SummaryFields({
  fields,
  draft,
  editableFields,
  onChange,
  directionError,
}: {
  fields: (typeof summaryFields)[number][]
  draft: SummaryDraft
  editableFields: Set<string>
  onChange: (key: SummaryKey, value: string | boolean) => void
  directionError: string | null
}) {
  return (
    <div className="grid gap-5 sm:grid-cols-2">
      {fields.map(([key, label, kind]) => {
        const editable = editableFields.has(key)
        const id = `summary-${key}`
        const unrestrictedKey =
          key === 'preferences.location'
            ? 'preferences.location_unrestricted'
            : key === 'preferences.employment_type'
              ? 'preferences.employment_type_unrestricted'
              : null
        const unrestricted = unrestrictedKey ? draft[unrestrictedKey] === true : false
        const options =
          key === 'preferences.employment_type'
            ? employmentOptions
            : key === 'preferences.work_mode'
              ? workModeOptions
              : null
        const value = String(draft[key])
        return (
          <div key={key}>
            <label htmlFor={id} className="mb-2 block text-sm">
              {label}
            </label>
            {kind === 'array' ? (
              <textarea
                id={id}
                className="textarea w-full resize-y rounded-xl border border-base-300 bg-base-200/25 text-sm leading-6"
                rows={key === 'target_directions' ? 2 : 3}
                value={value}
                readOnly={!editable}
                maxLength={10000}
                aria-invalid={key === 'target_directions' && Boolean(directionError)}
                aria-describedby={
                  key === 'target_directions' ? 'summary-directions-hint' : undefined
                }
                onChange={(event) => onChange(key, event.target.value)}
              />
            ) : options ? (
              <select
                id={id}
                className="select w-full rounded-xl border border-base-300 bg-base-100 text-sm"
                value={value}
                disabled={!editable || unrestricted}
                onChange={(event) => onChange(key, event.target.value)}
              >
                <option value="">{unrestricted ? 'No preference' : 'Not provided yet'}</option>
                {options.map(([option, optionLabel]) => (
                  <option key={option} value={option}>
                    {optionLabel}
                  </option>
                ))}
                {value && !options.some(([option]) => option === value) && (
                  <option value={value}>
                    {value === 'unrestricted' ? 'No preference' : value}
                  </option>
                )}
              </select>
            ) : (
              <input
                id={id}
                className="input w-full rounded-xl border border-base-300 bg-base-200/25 text-sm"
                value={value}
                readOnly={!editable}
                disabled={unrestricted}
                maxLength={10000}
                onChange={(event) => onChange(key, event.target.value)}
              />
            )}
            {key === 'target_directions' && (
              <p
                id="summary-directions-hint"
                className={`mt-2 text-xs ${directionError ? 'text-error' : 'text-base-content/55'}`}
              >
                {directionError ||
                  'Enter one item per line or separate items with commas. Choose up to three specific directions.'}
              </p>
            )}
            {unrestrictedKey && (
              <label className="mt-2.5 flex w-fit cursor-pointer items-center gap-2 text-xs text-base-content/65">
                <input
                  type="checkbox"
                  className="checkbox checkbox-xs"
                  checked={draft[unrestrictedKey] === true}
                  disabled={!editableFields.has(unrestrictedKey)}
                  onChange={(event) => onChange(unrestrictedKey, event.target.checked)}
                />
                {unrestrictedKey === 'preferences.location_unrestricted'
                  ? 'Any location'
                  : 'Any employment type'}
              </label>
            )}
          </div>
        )
      })}
    </div>
  )
}

export function SearchSummary({ summary }: { summary: Summary }) {
  const { answer, busy, session } = useScoutSession()
  const original = summaryDraft(summary.profile)
  const [formDraft, setFormDraft] = useSessionDraft('summary', { fields: original, message: '' })
  const { fields: draft, message } = formDraft
  const updates = summaryUpdates(original, draft, summary.editable_fields)
  const changed = Object.keys(updates).length > 0 || Boolean(message.trim())
  const editableFields = new Set(summary.editable_fields)
  const current = summary.revision === session?.revision
  const directionError = summaryDirectionError(draft)
  const onChange = (key: SummaryKey, value: string | boolean) =>
    setFormDraft({ ...formDraft, fields: { ...draft, [key]: value } })
  return (
    <form
      className="card border border-base-300 bg-base-100 p-5 sm:p-7"
      onSubmit={(event) => {
        event.preventDefault()
        if (changed && current && !busy && !directionError)
          answer({ action: 'edit_conditions', profile_updates: updates, message: message.trim() })
      }}
    >
      <h2 className="text-lg font-semibold">Review your profile and search criteria</h2>
      <p className="mt-3 text-sm leading-6 text-base-content/65">
        {summary.coverage_notice} Salary, industry, and work arrangement are preferences. We’ll flag
        details that haven’t been verified by the source.
      </p>
      <p className="mt-2 text-xs text-base-content/60">
        Enter one item per line or separate items with commas. After saving changes, review and
        confirm them. We won’t search for jobs until you confirm.
      </p>
      <fieldset disabled={busy} className="mt-6 min-w-0 space-y-6">
        <fieldset className="fieldset min-w-0 p-0">
          <legend className="fieldset-legend pb-3 text-sm">Your experience</legend>
          <SummaryFields
            fields={summaryFields
              .filter(([, , kind]) => kind === 'array')
              .filter(([key]) => key !== 'target_directions')}
            draft={draft}
            editableFields={editableFields}
            onChange={onChange}
            directionError={directionError}
          />
        </fieldset>
        <fieldset className="fieldset min-w-0 border-t border-base-300 p-0 pt-3">
          <legend className="fieldset-legend pb-3 text-sm">Search criteria</legend>
          <SummaryFields
            fields={summaryFields.filter(
              ([key, , kind]) =>
                kind !== 'boolean' &&
                (key === 'target_directions' || key.startsWith('preferences.')),
            )}
            draft={draft}
            editableFields={editableFields}
            onChange={onChange}
            directionError={directionError}
          />
        </fieldset>
        {summary.missing_fields.length > 0 && (
          <output className="block rounded-xl bg-accent/25 p-3 text-sm">
            Still to confirm:
            {summary.missing_fields.map(profileFieldLabel).join(', ')}
          </output>
        )}
        <div>
          <label htmlFor="summary-message" className="mb-2 block text-sm">
            Add or correct search criteria
          </label>
          <textarea
            id="summary-message"
            className="textarea min-h-24 w-full resize-y rounded-xl border border-base-300 bg-base-200/25 text-sm leading-6"
            value={message}
            onChange={(event) => setFormDraft({ ...formDraft, message: event.target.value })}
            maxLength={10000}
          />
        </div>
        <div className="flex flex-wrap gap-3 border-t border-base-300 pt-5">
          <button
            type="submit"
            disabled={!changed || !current || Boolean(directionError)}
            className="btn rounded-xl"
          >
            Save changes
          </button>
          <button
            type="button"
            disabled={
              changed || !summary.ready || summary.confirmed || !current || Boolean(directionError)
            }
            className="btn rounded-xl btn-primary"
            onClick={() => answer({ action: 'confirm_search' })}
          >
            Confirm and search
          </button>
        </div>
        {!current && (
          <p className="text-xs text-base-content/65">
            This summary is out of date. Refresh the session before confirming your search.
          </p>
        )}
        {changed && (
          <p className="text-xs text-base-content/65">
            You have unsaved changes. Save them and review the updated summary before confirming
            your search.
          </p>
        )}
      </fieldset>
    </form>
  )
}
