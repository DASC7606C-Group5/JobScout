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
  const { control } = useFormContext<ProfileFormValues>()
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
      <button
        type="button"
        disabled={reading}
        aria-label={resume ? `Remove resume: ${resume.name}` : 'Add a PDF, DOCX, or TXT resume'}
        aria-describedby="profile-error"
        className={`group flex w-full cursor-pointer items-center gap-4 rounded-field border border-dashed p-4 text-left transition-colors disabled:cursor-wait ${resume ? 'border-base-content/20 bg-base-200/20 hover:border-error hover:bg-error/10 hover:text-error focus-visible:border-error focus-visible:bg-error/10 focus-visible:text-error' : dragging ? 'border-primary-content bg-primary/15' : 'border-base-content/20 bg-base-200/20 hover:bg-base-200/45'}`}
        onClick={() => {
          if (resume) remove()
          else fileRef.current?.click()
        }}
        onDragOver={(event) => {
          event.preventDefault()
          if (!resume && !reading) setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault()
          setDragging(false)
          if (!resume && !reading) void attach(event.dataTransfer.files[0])
        }}
      >
        <span
          className={`flex size-10 shrink-0 items-center justify-center rounded-full bg-base-100 transition-colors ${resume ? 'group-hover:bg-error/10 group-focus-visible:bg-error/10' : ''}`}
        >
          {resume ? (
            <>
              <Icon name="file" className="group-hover:hidden group-focus-visible:hidden" />
              <Icon name="close" className="hidden group-hover:block group-focus-visible:block" />
            </>
          ) : (
            <Icon name="upload" />
          )}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-medium">
            {reading ? (
              'Parsing resume…'
            ) : resume ? (
              <>
                <span className="block truncate group-hover:hidden group-focus-visible:hidden">
                  {resume.name}
                </span>
                <span className="hidden group-hover:block group-focus-visible:block">
                  Remove resume
                </span>
              </>
            ) : (
              'Add a resume or drop it here'
            )}
          </span>
          <span
            className={`mt-1 block truncate text-xs text-base-content/55 ${resume ? 'group-hover:text-error group-focus-visible:text-error' : ''}`}
          >
            {resume ? (
              <>
                <span className="group-hover:hidden group-focus-visible:hidden">Resume added</span>
                <span className="hidden truncate group-hover:block group-focus-visible:block">
                  {resume.name}
                </span>
              </>
            ) : (
              'PDF / DOCX / TXT · Up to 10 MB · Optional'
            )}
          </span>
        </span>
        {resume && (
          <Icon
            name="check"
            className="shrink-0 text-primary-content group-hover:hidden group-focus-visible:hidden"
          />
        )}
      </button>
    </div>
  )
}
