import { useState } from 'react'
import { useFormContext, useWatch } from 'react-hook-form'

import type { ProfileFormValues } from '../../lib/profile-form'
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
      <label
        className={`relative flex cursor-pointer items-center gap-4 rounded-xl border border-dashed p-4 transition-colors ${dragging ? 'border-primary-content bg-primary/15' : 'border-base-content/20 bg-base-200/20 hover:bg-base-200/45'}`}
      >
        <input
          ref={fileRef}
          type="file"
          accept=".txt,text/plain"
          className="absolute inset-0 h-full w-full cursor-pointer opacity-0"
          aria-label="添加 TXT 简历"
          aria-describedby="profile-error"
          disabled={reading}
          onDragOver={(event) => {
            event.preventDefault()
            setDragging(true)
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(event) => {
            event.preventDefault()
            setDragging(false)
            if (!reading) void attach(event.dataTransfer.files[0])
          }}
          onChange={(event) => {
            void attach(event.target.files?.[0])
          }}
        />
        <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-base-100">
          <Icon name={resume ? 'file' : 'upload'} />
        </span>
        <span className="min-w-0">
          <span className="block truncate text-sm font-medium">
            {reading ? '正在读取简历…' : resume?.name || '添加简历，或者拖到这里'}
          </span>
          <span className="mt-1 block text-xs text-base-content/55">
            TXT · UTF-8 · 最大 1 MB · 可选
          </span>
        </span>
        {resume && <Icon name="check" className="ml-auto shrink-0 text-primary-content" />}
      </label>
      {resume && (
        <button type="button" className="btn mt-2 btn-ghost btn-xs" onClick={remove}>
          移除简历
        </button>
      )}
    </div>
  )
}
