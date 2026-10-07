import type { DraftStatus as Status } from '../state/draft-controller'
import { useNotification } from '../state/notifications'

export function DraftStatus({
  status,
  error,
  retry,
  reload,
  overwrite,
}: {
  status: Status
  error: Error | null
  retry: () => Promise<boolean>
  reload: () => Promise<boolean>
  overwrite: () => Promise<boolean>
}) {
  useNotification(status === 'error' || status === 'conflict' ? (error ?? status) : null, {
    id: 'draft-status',
    tone: 'warning',
    duration: Infinity,
    message:
      status === 'conflict'
        ? 'This draft was changed elsewhere. Your current input is still here.'
        : 'Could not save or load this draft. Your current input is still here.',
    actions:
      status === 'conflict'
        ? [
            { label: 'Reload draft', onClick: reload },
            { label: 'Save my version', onClick: overwrite },
          ]
        : [{ label: 'Try again', onClick: retry }],
  })
  if (status === 'error' || status === 'conflict') return null
  return (
    <output className="block text-xs text-base-content/60" aria-live="polite">
      {status === 'loading'
        ? 'Loading draft…'
        : status === 'saved'
          ? 'Draft saved'
          : status === 'saving'
            ? 'Saving draft…'
            : 'Changes waiting to save'}
    </output>
  )
}
