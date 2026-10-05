import { useEffect, useRef } from 'react'
import { useFormContext } from 'react-hook-form'

import type { ProfileFormValues } from '../../lib/profile-form'
import { readResume } from '../../lib/resume-client'

export function useResumeUpload(onReadingChange: (reading: boolean) => void) {
  const { setValue, setError, clearErrors } = useFormContext<ProfileFormValues>()
  const fileRef = useRef<HTMLInputElement>(null)
  const readId = useRef(0)
  const request = useRef<AbortController | null>(null)
  useEffect(
    () => () => {
      readId.current += 1
      request.current?.abort()
    },
    [],
  )

  async function attach(file: File | undefined) {
    if (!file) return
    const id = ++readId.current
    request.current?.abort()
    const controller = new AbortController()
    request.current = controller
    onReadingChange(true)
    clearErrors('root.resume')
    try {
      const resume = await readResume(file, controller.signal)
      if (id === readId.current) {
        setValue('resume', resume, { shouldDirty: true })
        clearErrors('description')
      }
    } catch (cause) {
      if (id === readId.current)
        setError('root.resume', {
          message:
            cause instanceof Error ? cause.message : 'Could not read the file. Please try again.',
        })
    }
    if (id !== readId.current) return
    request.current = null
    onReadingChange(false)
    if (fileRef.current) fileRef.current.value = ''
  }

  function remove() {
    readId.current += 1
    request.current?.abort()
    request.current = null
    onReadingChange(false)
    if (fileRef.current) fileRef.current.value = ''
    setValue('resume', null, { shouldDirty: true })
    clearErrors('root.resume')
  }
  return { fileRef, attach, remove }
}
