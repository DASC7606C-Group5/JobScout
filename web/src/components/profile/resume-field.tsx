import { useState } from 'react'
import { useFormContext, useWatch } from 'react-hook-form'

import type { ProfileFormValues } from '../../lib/profile-form'
import { RESUME_FILE_ACCEPT } from '../../lib/resume-client'
import { Icon } from '../icon'
import { useResumeUpload } from './use-resume-upload'

export function ResumeField({
  reading,
  onReadingChange,
}: {
  reading: boolean
  onReadingChange: (reading: boolean) => void
}) {
  const {
    control,
    formState: { errors },
  } = useFormContext<ProfileFormValues>()
  const resume = useWatch({ control, name: 'resume' })
  const [dragging, setDragging] = useState(false)
  const { fileRef, attach, remove } = useResumeUpload(onReadingChange)
  return (
    <div>
      <input
        ref={fileRef}
        type="file"
        accept={RESUME_FILE_ACCEPT}
        hidden
        disabled={reading}
        onChange={(event) => {
          void attach(event.target.files?.[0])
        }}
      />
      {resume ? (
        <div className="flex flex-wrap items-center gap-3 rounded-field border border-base-300 px-6 py-4">
          <Icon name="file" className="shrink-0 text-primary-content" />
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium break-all">{resume.name}</p>
            <output className="mt-1 block text-xs text-base-content/65">
              {reading ? 'Parsing resume…' : 'Resume added'}
            </output>
          </div>
          <div className="flex gap-1">
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              disabled={reading}
              onClick={() => fileRef.current?.click()}
            >
              Replace resume
            </button>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              disabled={reading}
              aria-label={`Remove resume: ${resume.name}`}
              onClick={remove}
            >
              Remove
            </button>
          </div>
        </div>
      ) : (
        <button
          type="button"
          disabled={reading}
          aria-label="Add a PDF, DOCX, or TXT resume"
          aria-describedby="resume-error"
          className={`flex w-full items-center gap-3 rounded-field border border-dashed px-6 py-4 text-left disabled:cursor-wait ${dragging ? 'border-primary-content bg-primary/15' : 'border-base-content/20 hover:bg-base-200/45'}`}
          onClick={() => fileRef.current?.click()}
          onDragOver={(event) => {
            event.preventDefault()
            if (!reading) setDragging(true)
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(event) => {
            event.preventDefault()
            setDragging(false)
            if (!reading) void attach(event.dataTransfer.files[0])
          }}
        >
          <Icon name="upload" className="shrink-0" />
          <span className="min-w-0">
            <span className="block text-sm font-medium">
              {reading ? 'Parsing resume…' : 'Add a resume or drop it here'}
            </span>
            <span className="mt-1 block text-xs text-base-content/65">
              PDF / DOCX / TXT · Up to 10 MB
            </span>
          </span>
        </button>
      )}
      {errors.root?.resume && (
        <p id="resume-error" role="alert" className="mt-2 text-sm text-error">
          {errors.root.resume.message}
        </p>
      )}
    </div>
  )
}
