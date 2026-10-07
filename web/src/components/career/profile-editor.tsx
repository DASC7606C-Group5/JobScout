import { useState } from 'react'

import type { Background, PersonalProfile } from '../../lib/career-contracts'
import { useCurrentProfile, useSaveProfile } from '../../state/career-queries'

export function PersonalProfileEditor() {
  const query = useCurrentProfile()
  if (query.isPending) return <output>Loading current profile…</output>
  if (!query.data) return <p role="alert">Your profile could not be loaded.</p>
  return <ProfileEditor key={query.data.revision} current={query.data} />
}

function ProfileEditor({ current }: { current: PersonalProfile }) {
  const [description, setDescription] = useState(current.description)
  const [resumeName, setResumeName] = useState(current.resume?.name ?? '')
  const [resumeText, setResumeText] = useState(current.resume?.text ?? '')
  const [background, setBackground] = useState(current.background)
  const save = useSaveProfile()
  return (
    <form
      className="max-w-3xl"
      onSubmit={(event) => {
        event.preventDefault()
        save.mutate({
          expected_revision: current.revision,
          description,
          resume: resumeText ? { name: resumeName || 'Resume', text: resumeText } : null,
          background,
          documents: current.documents,
        })
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
          value={description}
          onChange={(event) => setDescription(event.target.value)}
        />
        <label className="label" htmlFor="personal-resume-name">
          Resume name
        </label>
        <textarea
          id="personal-resume-name"
          className="textarea w-full"
          rows={1}
          value={resumeName}
          onChange={(event) => setResumeName(event.target.value)}
        />
        <label className="label" htmlFor="personal-resume">
          Original resume text
        </label>
        <textarea
          id="personal-resume"
          className="textarea w-full"
          value={resumeText}
          onChange={(event) => setResumeText(event.target.value)}
        />
        {(['education', 'skills', 'internships', 'projects'] as (keyof Background)[]).map(
          (field) => (
            <label key={field} className="space-y-2">
              <span className="label capitalize">{field} · one entry per line</span>
              <textarea
                className="textarea w-full"
                value={background[field].join('\n')}
                onChange={(event) =>
                  setBackground({ ...background, [field]: event.target.value.split('\n') })
                }
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
