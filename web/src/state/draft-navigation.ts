interface PendingDraft {
  hasPending: () => boolean
  flush: () => Promise<boolean>
  discard: () => void
}

const drafts = new Map<PendingDraft, string>()

export function discardAllDrafts() {
  for (const draft of drafts.keys()) draft.discard()
  drafts.clear()
}

export function registerDraft(draft: PendingDraft, path: string) {
  drafts.set(draft, path)
  return () => {
    drafts.delete(draft)
  }
}

export function hasPendingDrafts() {
  return [...drafts.keys()].some((draft) => draft.hasPending())
}

export async function flushPendingDrafts() {
  const results = await Promise.all(
    [...drafts.keys()].filter((draft) => draft.hasPending()).map((draft) => draft.flush()),
  )
  return results.every(Boolean)
}

export function discardSessionDrafts(id: string, revision?: number) {
  const prefix = `/sessions/${encodeURIComponent(id)}/drafts/${revision === undefined ? '' : `${revision}/`}`
  for (const [draft, path] of drafts) {
    if (path.startsWith(prefix)) {
      draft.discard()
      drafts.delete(draft)
    }
  }
}
