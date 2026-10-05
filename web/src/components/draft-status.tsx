import type { DraftStatus as Status } from '../state/draft-controller'

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
  if (status === 'error' || status === 'conflict')
    return (
      <div className="alert alert-soft alert-warning sm:alert-horizontal" role="alert">
        <div>
          <p className="text-sm">
            {status === 'conflict'
              ? 'This draft was changed elsewhere. Your current input is still here.'
              : 'Could not save or load this draft. Your current input is still here.'}
          </p>
          {error && <p className="mt-1 text-xs">{error.message}</p>}
          <div className="mt-3 flex flex-wrap gap-2">
            {status === 'conflict' ? (
              <>
                <button
                  type="button"
                  className="btn btn-sm"
                  onClick={() => {
                    void reload()
                  }}
                >
                  Reload draft
                </button>
                <button
                  type="button"
                  className="btn btn-sm"
                  onClick={() => {
                    void overwrite()
                  }}
                >
                  Save my version
                </button>
              </>
            ) : (
              <button
                type="button"
                className="btn btn-sm"
                onClick={() => {
                  void retry()
                }}
              >
                Try again
              </button>
            )}
          </div>
        </div>
      </div>
    )
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
