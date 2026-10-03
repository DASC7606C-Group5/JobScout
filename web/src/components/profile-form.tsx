import { useEffect, useState } from 'react'
import { FormProvider, useForm } from 'react-hook-form'

import { toScoutInput, type ProfileFormValues } from '../lib/profile-form'
import { useScoutStore } from '../state/scout-context'
import { useScoutSession } from '../state/session-context'
import { Icon } from './icon'
import { DescriptionField } from './profile/description-field'
import { DirectionField } from './profile/direction-field'
import { PreferenceFields } from './profile/preference-fields'
import { ResumeField } from './profile/resume-field'

export function ProfileForm() {
  const store = useScoutStore()
  const { start } = useScoutSession()
  const form = useForm<ProfileFormValues>({ defaultValues: store.getState().draft })
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
        callback: ({ values }) => store.getState().saveDraft(values),
      }),
    [subscribe, store],
  )
  const error = errors.description?.message || errors.root?.resume?.message

  return (
    <FormProvider {...form}>
      <form
        noValidate
        className="card border border-base-300 bg-base-100 shadow-sm"
        onSubmit={(event) => {
          if (reading) {
            event.preventDefault()
            return
          }
          void handleSubmit((values) => start(toScoutInput(values)))(event)
        }}
      >
        <div className="border-b border-base-300 px-5 py-5 sm:px-7">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <span className="flex size-10 items-center justify-center rounded-xl bg-secondary/45">
                <Icon name="file" />
              </span>
              <div>
                <h2 className="text-lg font-semibold">先认识一下你</h2>
                <p className="mt-1 text-xs text-base-content/60">你的经历，是发现好机会的起点</p>
              </div>
            </div>
          </div>
        </div>
        <fieldset disabled={reading} className="min-w-0 space-y-6 p-5 sm:p-7">
          <DescriptionField />
          <ResumeField reading={reading} onReadingChange={setReading} />
          <DirectionField />
          <PreferenceFields />
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
              {reading ? '正在读取…' : '发现适合我的机会'}
              <Icon name="arrow" size={18} />
            </button>
          </div>
        </fieldset>
      </form>
    </FormProvider>
  )
}
