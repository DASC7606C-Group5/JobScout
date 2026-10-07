import { Controller, useForm } from 'react-hook-form'

import type { Background, PersonalProfile } from '../../lib/career-contracts'
import { useCurrentProfile, useSaveProfile } from '../../state/career-queries'

export function PersonalProfileEditor() {
  const query = useCurrentProfile()
  if (query.isPending) return <output>Loading current profile…</output>
  if (!query.data) return <p role="alert">Your profile could not be loaded.</p>
  return <ProfileEditor key={query.data.revision} current={query.data} />
}

function ProfileEditor({ current }: { current: PersonalProfile }) {
  const form = useForm<{
    description: string
    resumeName: string
    resumeText: string
    background: Background
  }>({
    defaultValues: {
      description: current.description,
      resumeName: current.resume?.name ?? '',
      resumeText: current.resume?.text ?? '',
      background: current.background,
    },
  })
  const save = useSaveProfile()
  return (
    <form
      className="max-w-3xl"
      onSubmit={(event) => {
        void form.handleSubmit(({ description, resumeName, resumeText, background }) => {
          save.mutate({
            expected_revision: current.revision,
            description,
            resume: resumeText ? { name: resumeName || 'Resume', text: resumeText } : null,
            background,
            documents: current.documents,
          })
        })(event)
      }}
    >
      <fieldset className="fieldset" disabled={save.isPending}>
        <legend className="fieldset-legend">
          Current personal profile · revision {current.revision}
        </legend>
        <p>
          Your background is reused across tasks. Each task keeps its own directions and
          preferences.
        </p>
        <label className="label" htmlFor="personal-description">
          Original description
        </label>
        <textarea
          id="personal-description"
          className="textarea w-full"
          {...form.register('description')}
        />
        <label className="label" htmlFor="personal-resume-name">
          Resume name
        </label>
        <textarea
          id="personal-resume-name"
          className="textarea w-full"
          rows={1}
          {...form.register('resumeName')}
        />
        <label className="label" htmlFor="personal-resume">
          Original resume text
        </label>
        <textarea
          id="personal-resume"
          className="textarea w-full"
          {...form.register('resumeText')}
        />
        {(['education', 'skills', 'internships', 'projects'] as (keyof Background)[]).map(
          (field) => (
            <label key={field} className="space-y-2">
              <span className="label capitalize">{field} · one entry per line</span>
              <Controller
                control={form.control}
                name={`background.${field}`}
                render={({ field: control }) => (
                  <textarea
                    className="textarea w-full"
                    value={control.value.join('\n')}
                    onBlur={control.onBlur}
                    ref={control.ref}
                    onChange={(event) => control.onChange(event.target.value.split('\n'))}
                  />
                )}
              />
            </label>
          ),
        )}
        <p>Evidence documents: {current.documents.length}</p>
        {current.documents.map((document) => (
          <details key={document.document_id}>
            <summary>{document.document_id}</summary>
            <p className="whitespace-pre-wrap">{document.text}</p>
          </details>
        ))}
        <button className="btn" type="submit">
          Save current profile
        </button>
        {save.isError && (
          <p role="alert">Profile could not be saved. Reload to check the current revision.</p>
        )}
        {save.isSuccess && <output>Profile saved.</output>}
      </fieldset>
    </form>
  )
}
