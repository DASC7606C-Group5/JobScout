import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Controller, useFormContext, useWatch } from 'react-hook-form'

import type { ProfileFormValues } from '../../lib/profile-form'
import { RESUME_FILE_ACCEPT, readResumeLimits } from '../../lib/resume-client'
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
    getValues,
    formState: { errors },
  } = useFormContext<ProfileFormValues>()
  const resume = useWatch({ control, name: 'resume' })
  const limits = useQuery({
    queryKey: ['resume-limits'],
    queryFn: ({ signal }) => readResumeLimits(signal),
    staleTime: 60_000,
  })
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
        <>
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
                aria-busy={reading}
                onClick={() => fileRef.current?.click()}
              >
                {reading && (
                  <span className="loading loading-xs loading-spinner" aria-hidden="true" />
                )}
                Replace
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
          <div className="mt-3">
            <Controller
              control={control}
              name="resume_consent"
              rules={{
                validate: (value) =>
                  getValues('resume') && !value
                    ? 'Confirm that you consent to sending your resume to the configured AI model.'
                    : true,
              }}
              render={({ field, fieldState }) => (
                <>
                  <label className="flex cursor-pointer items-center gap-3 rounded-field border border-base-300 bg-base-200/45 px-4 py-3">
                    <input
                      type="checkbox"
                      className="checkbox shrink-0 rounded-full checkbox-primary"
                      name={field.name}
                      aria-invalid={fieldState.invalid}
                      checked={field.value}
                      onChange={(event) => field.onChange(event.target.checked)}
                      onBlur={field.onBlur}
                      ref={field.ref}
                    />
                    <span className="text-sm text-base-content/80">
                      I agree to send my resume to the configured AI model for profile analysis.
                    </span>
                  </label>
                  {fieldState.error && (
                    <p role="alert" className="mt-2 text-sm text-error">
                      {fieldState.error.message}
                    </p>
                  )}
                </>
              )}
            />
          </div>
        </>
      ) : (
        <button
          type="button"
          disabled={reading}
          aria-busy={reading}
          aria-label="Add a PDF, DOCX, or TXT resume"
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
          {reading ? (
            <span className="loading loading-sm loading-spinner" aria-hidden="true" />
          ) : (
            <Icon name="upload" className="shrink-0" />
          )}
          <span className="min-w-0">
            <span className="block text-sm font-medium">
              {reading ? 'Parsing resume…' : 'Add a resume or drop it here'}
            </span>
            <span className="mt-1 block text-xs text-base-content/65">
              PDF / DOCX / TXT
              {limits.data &&
                ` · Up to ${limits.data.max_bytes / 1024 / 1024} MiB · PDF: ${limits.data.max_pdf_pages} pages · ${limits.data.max_text_characters.toLocaleString()} characters`}
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
