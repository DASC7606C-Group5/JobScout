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
import { SummaryValues } from './profile/profile-summary'
import { ResultCountField } from './profile/result-count-field'
import { SummaryGroup } from './profile/summary-group'

const workModeOptions = [
  ['onsite', 'On-site'],
  ['hybrid', 'Hybrid'],
  ['remote', 'Remote'],
] as const

const groups = [
  {
    title: 'Search conditions',
    keys: [
      'target_directions',
      'preferences.location',
      'preferences.location_unrestricted',
      'preferences.employment_type',
      'preferences.employment_type_unrestricted',
    ],
  },
  { title: 'Experience', keys: ['education', 'skills', 'internships', 'projects'] },
  {
    title: 'Other preferences',
    keys: [
      'preferences.salary_range',
      'preferences.work_mode',
      'preferences.industry',
      'search_options.result_count',
    ],
  },
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
        if (kind === 'number')
          return (
            <ResultCountField
              key={key}
              id="summary-result-count"
              value={Number(draft[key])}
              onChange={(value) => onChange(key, value)}
              disabled={!editable}
            />
          )
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
      className="card border border-base-300 bg-base-100 p-5 sm:p-6"
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
      {summary.coverage_notice && (
        <p className="mb-4 text-sm leading-6 text-base-content/65">{summary.coverage_notice}</p>
      )}
      <fieldset
        disabled={busy || persisted.status === 'loading'}
        className="min-w-0 space-y-5 sm:space-y-6"
      >
        <SummarySections
          summary={summary}
          draft={draft}
          original={original}
          editableFields={editableFields}
          invalid={invalid}
          onChange={onChange}
        />
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
        <div className="-mx-5 flex flex-wrap items-center justify-between gap-3 border-t border-base-300 px-5 pt-5 sm:-mx-6 sm:px-6 sm:pt-6">
          <DraftStatus {...persisted} />
          {changed ? (
            <button type="submit" disabled={!canSave} className="btn btn-primary">
              Update criteria
            </button>
          ) : (
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
          )}
        </div>
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
            Update your criteria and review the updated summary before confirming your search.
          </p>
        )}
      </fieldset>
    </form>
  )
}

function SummarySections({
  summary,
  draft,
  original,
  editableFields,
  invalid,
  onChange,
}: {
  summary: Summary
  draft: SummaryDraft
  original: SummaryDraft
  editableFields: Set<string>
  invalid: boolean
  onChange: (key: SummaryKey, value: string | boolean | number) => void
}) {
  const missing = [
    ...new Set([...summary.missing_fields, ...summary.profile.missing_required_fields]),
  ]
  const unresolved = summary.profile.preferences.locations.included.filter(
    (place) => place.resolution !== 'resolved',
  )
  return (
    <>
      {(missing.length > 0 || summary.profile.conflicts.length > 0 || unresolved.length > 0) && (
        <output className="block rounded-box bg-accent/20 p-3 text-sm">
          {missing.length > 0 && (
            <p>Still to confirm: {missing.map(profileFieldLabel).join(', ')}</p>
          )}
          {summary.profile.conflicts.map((conflict) => (
            <p key={conflict}>{conflict}</p>
          ))}
          {unresolved.length > 0 && (
            <p>Clarify location: {unresolved.map((place) => place.name).join(', ')}</p>
          )}
        </output>
      )}
      {groups.map((group) => {
        const keys = new Set<string>(group.keys)
        const fields = summaryFields.filter(([key]) => keys.has(key))
        const dirty = fields.some(([key]) => draft[key] !== original[key])
        const attention =
          missing.some((key) => keys.has(key)) ||
          (group.title === 'Search conditions' &&
            (unresolved.length > 0 || summary.profile.conflicts.length > 0)) ||
          (group.title === 'Other preferences' && invalid)
        return (
          <SummaryGroup
            key={group.title}
            title={group.title}
            changed={dirty}
            needsAttention={attention}
            editable={fields.some(([key]) => editableFields.has(key))}
            summary={<SummaryValues fields={fields} draft={draft} profile={summary.profile} />}
          >
            <SummaryFields
              fields={fields.filter(([, , kind]) => kind !== 'boolean')}
              draft={draft}
              editableFields={editableFields}
              onChange={onChange}
            />
          </SummaryGroup>
        )
      })}
    </>
  )
}
