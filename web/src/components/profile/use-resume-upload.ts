import { useEffect, useRef } from 'react'
import { useFormContext } from 'react-hook-form'

import type { ProfileFormValues } from '../../lib/profile-form'
import { readResume } from '../../lib/session-client'

export function useResumeUpload(onReadingChange: (reading: boolean) => void) {
  const { setValue, setError, clearErrors } = useFormContext<ProfileFormValues>()
  const fileRef = useRef<HTMLInputElement>(null)
  const readId = useRef(0)
  useEffect(
    () => () => {
      readId.current += 1
    },
    [],
  )

  async function attach(file: File | undefined) {
    if (!file) return
    const id = ++readId.current
    onReadingChange(true)
    clearErrors('root.resume')
    try {
      const resume = await readResume(file)
      if (id === readId.current) {
        setValue('resume', resume, { shouldDirty: true })
        clearErrors('description')
      }
    } catch (cause) {
      if (id === readId.current)
        setError('root.resume', {
          message: cause instanceof Error ? cause.message : '文件读取失败，请重试。',
        })
    }
    if (id !== readId.current) return
    onReadingChange(false)
    if (fileRef.current) fileRef.current.value = ''
  }

  function remove() {
    setValue('resume', null, { shouldDirty: true })
    clearErrors('root.resume')
  }
  return { fileRef, attach, remove }
}
