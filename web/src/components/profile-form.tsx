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
  const { subscribe, handleSubmit } = form
  const [reading, setReading] = useState(false)
  useEffect(
    () =>
      subscribe({
        formState: { values: true },
        callback: ({ values }) => saveDraft(values),
      }),
    [subscribe, saveDraft],
  )

  return (
    <FormProvider {...form}>
      <form
        noValidate
        className="card border border-base-300 bg-base-100"
        onCompositionStart={draft.onCompositionStart}
        onCompositionEnd={draft.onCompositionEnd}
        onSubmit={(event) => {
          if (reading) {
            event.preventDefault()
            return
          }
          void handleSubmit(
            (values) => {
              void start(toScoutInput(values))
            },
            () => {
              requestAnimationFrame(() => {
                document.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus()
              })
            },
          )(event)
        }}
      >
        <fieldset
          disabled={reading || busy || draft.status === 'loading'}
          className="min-w-0 space-y-5 p-5 sm:space-y-6 sm:p-6"
        >
          <div>
            <h2 className="text-sm font-semibold">Your experience</h2>
          </div>
          <ResumeField reading={reading} onReadingChange={setReading} />
          <DescriptionField />
          <DirectionField />
          <PreferenceFields />
          <div className="-mx-5 flex flex-wrap items-center justify-between gap-3 border-t border-base-300 px-5 pt-5 sm:-mx-6 sm:px-6 sm:pt-6">
            <DraftStatus {...draft} />
            <button type="submit" className="btn min-w-40 border-0 btn-primary" disabled={reading}>
              {reading ? 'Reading…' : 'Analyze and continue'}
              <Icon name="arrow" size={18} />
            </button>
          </div>
        </fieldset>
      </form>
    </FormProvider>
  )
}
