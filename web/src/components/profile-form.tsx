import { useEffect, useState } from 'react'
import { FormProvider, useForm } from 'react-hook-form'

import { createExampleDraft, toScoutInput, type ProfileFormValues } from '../lib/profile-form'
import { useScoutStore } from '../state/scout-context'
import { Icon } from './icon'
import { DescriptionField } from './profile/description-field'
import { DirectionField } from './profile/direction-field'
import { PreferenceFields } from './profile/preference-fields'
import { ResumeField } from './profile/resume-field'

export function ProfileForm() {
  const store = useScoutStore()
  const form = useForm<ProfileFormValues>({ defaultValues: store.getState().draft })
  const {
    subscribe,
    reset,
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
          void handleSubmit((values) => store.getState().start(toScoutInput(values)))(event)
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
            <button
              type="button"
              className="btn btn-ghost font-normal text-base-content/70 btn-sm"
              onClick={() => reset(createExampleDraft())}
              disabled={reading}
            >
              <Icon name="sparkles" size={15} />
              填入示例
            </button>
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
          <div className="flex flex-wrap items-center justify-between gap-4 border-t border-base-300 pt-5">
            <p className="max-w-64 text-xs leading-5 text-base-content/55">
              资料仅在当前工作空间中使用，刷新后清空。
              <br />
              示例模式不会上传你的简历或个人信息。
            </p>
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
