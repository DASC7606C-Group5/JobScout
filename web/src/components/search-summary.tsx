import type { SearchSummary as Summary } from '../lib/contracts'
import { profileFieldLabel } from '../lib/conversation'
import { resultCountError } from '../lib/profile-form'
import {
  summaryDraft,
  summaryFields,
  summaryUpdates,
  type SummaryDraft,
  type SummaryKey,
} from '../lib/search-summary'
import { useScoutSession } from '../state/session-context'
import { useSessionDraft } from '../state/use-session-draft'
import { DraftStatus } from './draft-status'
import { InterpretedConditions } from './profile/interpreted-conditions'
import { ResultCountField } from './profile/result-count-field'

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
}: {
  fields: (typeof summaryFields)[number][]
  draft: SummaryDraft
  editableFields: Set<string>
  onChange: (key: SummaryKey, value: string | boolean | number) => void
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
        const options = key === 'preferences.work_mode' ? workModeOptions : null
        const value = String(draft[key])
        return (
          <div key={key}>
            <label htmlFor={id} className="mb-2 block text-sm">
              {label}
            </label>
            {kind === 'array' ? (
              <textarea
                id={id}
                className="textarea field-sizing-content max-h-96 min-h-24 w-full resize-none border border-base-300 bg-base-200/25 text-sm leading-6"
                rows={key === 'target_directions' ? 2 : 3}
                value={value}
                readOnly={!editable}
                maxLength={10000}
                aria-describedby={
                  key === 'target_directions' ? 'summary-directions-hint' : undefined
                }
                onChange={(event) => onChange(key, event.target.value)}
              />
            ) : options ? (
              <select
                id={id}
                className="select w-full border border-base-300 bg-base-100 text-sm"
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
                className="input w-full border border-base-300 bg-base-200/25 text-sm"
                value={value}
                readOnly={!editable}
                disabled={unrestricted}
                maxLength={10000}
                onChange={(event) => onChange(key, event.target.value)}
              />
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
  const { answer, busy, session, refresh } = useScoutSession()
  const original = summaryDraft(summary.profile)
  const persisted = useSessionDraft('summary', { fields: original, message: '' })
  const { value: formDraft, setValue: setFormDraft } = persisted
  const { fields: draft, message } = formDraft
  const updates = summaryUpdates(original, draft, summary.editable_fields)
  const count = Number(draft['search_options.result_count'])
  const countChanged = count !== original['search_options.result_count']
  const countError = resultCountError(count)
  const changed = Object.keys(updates).length > 0 || countChanged || Boolean(message.trim())
  const editableFields = new Set(summary.editable_fields)
  const current = summary.revision === session?.revision
  const invalid = Boolean(countError)
  const canSave = changed && current && !invalid
  const canConfirm = !changed && summary.ready && !summary.confirmed && current && !invalid
  const onChange = (key: SummaryKey, value: string | boolean | number) =>
    setFormDraft({ ...formDraft, fields: { ...draft, [key]: value } })
  return (
    <form
      noValidate
      className="card border border-base-300 bg-base-100 p-5 sm:p-7"
      onCompositionStart={persisted.onCompositionStart}
      onCompositionEnd={persisted.onCompositionEnd}
      onSubmit={(event) => {
        event.preventDefault()
        if (canSave && !busy)
          void answer({
            action: 'edit_conditions',
            profile_updates: updates,
            message: message.trim(),
            ...(countChanged ? { search_options: { result_count: count } } : {}),
          })
      }}
    >
      <h2 className="text-lg font-semibold">Review your profile and search criteria</h2>
      <p className="mt-3 text-sm leading-6 text-base-content/65">{summary.coverage_notice}</p>
      <fieldset
        disabled={busy || persisted.status === 'loading'}
        className="mt-6 min-w-0 space-y-6"
      >
        <fieldset className="fieldset min-w-0 p-0">
          <legend className="fieldset-legend pb-3 text-sm">Your experience</legend>
          <SummaryFields
            fields={summaryFields
              .filter(([, , kind]) => kind === 'array')
              .filter(([key]) => key !== 'target_directions')}
            draft={draft}
            editableFields={editableFields}
            onChange={onChange}
          />
        </fieldset>
        <ResultCountField
          id="summary-result-count"
          value={count}
          onChange={(value) => onChange('search_options.result_count', value)}
          disabled={!editableFields.has('search_options.result_count')}
        />
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
          />
        </fieldset>
        {!changed && <InterpretedConditions preferences={summary.profile.preferences} />}
        {summary.missing_fields.length > 0 && (
          <output className="block rounded-box bg-accent/25 p-3 text-sm">
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
            className="textarea field-sizing-content max-h-96 min-h-24 w-full resize-none border border-base-300 bg-base-200/25 text-sm leading-6"
            value={message}
            onChange={(event) => setFormDraft({ ...formDraft, message: event.target.value })}
            maxLength={10000}
          />
        </div>
        <div className="flex flex-wrap gap-3 border-t border-base-300 pt-5">
          <button type="submit" disabled={!canSave} className="btn">
            Save changes
          </button>
          <button
            type="button"
            disabled={!canConfirm}
            className="btn btn-primary"
            onClick={() => {
              void answer({ action: 'confirm_search' })
            }}
          >
            Confirm and search
          </button>
        </div>
        <DraftStatus {...persisted} />
        {!current && (
          <div className="text-xs text-base-content/65">
            <p>Your search has changed. Reload it before confirming these criteria.</p>
            <button type="button" className="btn mt-2 btn-ghost btn-sm" onClick={refresh}>
              Reload search
            </button>
          </div>
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
