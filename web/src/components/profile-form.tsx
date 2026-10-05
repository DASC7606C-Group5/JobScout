import { useEffect, useState } from 'react'
import { FormProvider, useForm } from 'react-hook-form'

import { createProfileDraft, toScoutInput, type ProfileFormValues } from '../lib/profile-form'
import { workspaceDraftPath } from '../lib/workspace-client'
import { useScoutSession } from '../state/session-context'
import { usePersistedDraft } from '../state/use-persisted-draft'
import { DraftStatus } from './draft-status'
import { Icon } from './icon'
import { DescriptionField } from './profile/description-field'
import { DirectionField } from './profile/direction-field'
import { PreferenceFields } from './profile/preference-fields'
import { ResumeField } from './profile/resume-field'

export function ProfileForm() {
  const draft = usePersistedDraft(workspaceDraftPath, createProfileDraft())
  const { setValue: saveDraft } = draft
  const { start, busy } = useScoutSession()
  const form = useForm<ProfileFormValues>({ values: draft.value })
  const {
    subscribe,
    handleSubmit,
    formState: { errors },
  } = form
  const [reading, setReading] = useState(false)
  useEffect(
    () =>
      subscribe({
        formState: { values: true },
        callback: ({ values }) => saveDraft(values),
      }),
    [subscribe, saveDraft],
  )
  const error = errors.description?.message || errors.root?.resume?.message

  return (
    <FormProvider {...form}>
      <form
        noValidate
        className="card border border-base-300 bg-base-100 shadow-sm"
        onCompositionStart={draft.onCompositionStart}
        onCompositionEnd={draft.onCompositionEnd}
        onSubmit={(event) => {
          if (reading) {
            event.preventDefault()
            return
          }
          void handleSubmit((values) => {
            void start(toScoutInput(values))
          })(event)
        }}
      >
        <div className="border-b border-base-300 px-5 py-5 sm:px-7">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <span className="flex size-10 items-center justify-center rounded-xl bg-secondary/45">
                <Icon name="file" />
              </span>
              <div>
                <h2 className="text-lg font-semibold">Let’s get to know you</h2>
                <p className="mt-1 text-xs text-base-content/60">
                  Your experience is a great place to start.
                </p>
              </div>
            </div>
          </div>
        </div>
        <fieldset
          disabled={reading || busy || draft.status === 'loading'}
          className="min-w-0 space-y-6 p-5 sm:p-7"
        >
          <DescriptionField />
          <ResumeField reading={reading} onReadingChange={setReading} />
          <DirectionField />
          <PreferenceFields />
          <DraftStatus {...draft} />
          <div id="profile-error" hidden={!error}>
            {error && (
              <div className="alert rounded-xl alert-soft text-sm alert-error" role="alert">
                <Icon name="info" size={18} />
                {error}
              </div>
            )}
          </div>
          <div className="flex flex-wrap items-center justify-end gap-4 border-t border-base-300 pt-5">
            <button
              type="submit"
              className="btn min-w-40 rounded-xl border-0 btn-primary"
              disabled={reading}
            >
              {reading ? 'Reading…' : 'Analyze and continue'}
              <Icon name="arrow" size={18} />
            </button>
          </div>
        </fieldset>
      </form>
    </FormProvider>
  )
}
