import { SessionHttpError } from '../lib/api-client'
import type { DraftResponse, SaveDraftRequest } from '../lib/contracts'

export type DraftStatus = 'loading' | 'saved' | 'unsaved' | 'saving' | 'error' | 'conflict'

export interface DraftSnapshot<T> {
  value: T
  status: DraftStatus
  revision: number
  updatedAt: string | null
  error: Error | null
}

export class DraftController<T extends object> {
  private snapshot: DraftSnapshot<T>
  private listeners = new Set<() => void>()
  private timer: ReturnType<typeof setTimeout> | null = null
  private version = 0
  private savedVersion = 0
  private composing = false
  private loaded = false
  private discarded = false
  private operation: Promise<boolean> | null = null
  private request: { version: number; payload: SaveDraftRequest<T> } | null = null

  constructor(
    private initial: T,
    private save: (request: SaveDraftRequest<T>) => Promise<DraftResponse<T>>,
    private read: () => Promise<DraftResponse<T>>,
    private committed: (response: DraftResponse<T>) => void = () => {},
    private delay = 500,
  ) {
    this.snapshot = {
      value: structuredClone(initial),
      status: 'loading',
      revision: 0,
      updatedAt: null,
      error: null,
    }
  }

  getSnapshot = () => this.snapshot
  isDiscarded = () => this.discarded
  subscribe = (listener: () => void) => {
    this.listeners.add(listener)
    return () => this.listeners.delete(listener)
  }
  private publish(update: Partial<DraftSnapshot<T>>) {
    this.snapshot = { ...this.snapshot, ...update }
    for (const listener of this.listeners) listener()
  }

  hydrate(response: DraftResponse<T>) {
    if (this.discarded || (this.loaded && response.revision < this.snapshot.revision)) return
    if (this.hasPending()) return
    this.loaded = true
    const value = Object.keys(response.data).length ? response.data : this.initial
    if (this.snapshot.revision === response.revision && this.snapshot.status === 'saved') return
    this.publish({
      value: structuredClone(value),
      status: 'saved',
      revision: response.revision,
      updatedAt: response.updated_at,
      error: null,
    })
  }

  loadFailed(error: Error) {
    if (!this.discarded && !this.loaded) this.publish({ status: 'error', error })
  }

  update = (update: T | ((value: T) => T)) => {
    if (this.discarded) return
    const value = typeof update === 'function' ? update(this.snapshot.value) : update
    if (JSON.stringify(value) === JSON.stringify(this.snapshot.value)) return
    this.version += 1
    this.publish({
      value: structuredClone(value),
      status: !this.loaded
        ? this.snapshot.status
        : this.snapshot.status === 'conflict'
          ? 'conflict'
          : 'unsaved',
      error: !this.loaded || this.snapshot.status === 'conflict' ? this.snapshot.error : null,
    })
    this.schedule()
  }

  private schedule() {
    if (this.timer) clearTimeout(this.timer)
    this.timer = null
    if (this.composing || !this.loaded || this.snapshot.status === 'conflict') return
    this.timer = setTimeout(() => {
      this.timer = null
      void this.flush()
    }, this.delay)
  }

  setComposing = (value: boolean) => {
    if (this.discarded) return
    this.composing = value
    if (value && this.timer) {
      clearTimeout(this.timer)
      this.timer = null
    } else if (!value && this.hasPending()) this.schedule()
  }

  hasPending = () =>
    !this.discarded &&
    (this.version !== this.savedVersion || this.operation !== null || this.composing)

  discard = () => {
    this.discarded = true
    if (this.timer) clearTimeout(this.timer)
    this.timer = null
    this.request = null
    this.savedVersion = this.version
    this.publish({ value: structuredClone(this.initial), status: 'saved', error: null })
  }

  flush = (): Promise<boolean> => {
    if (this.discarded) return Promise.resolve(true)
    if (this.timer) clearTimeout(this.timer)
    this.timer = null
    if (this.operation) return this.operation
    if (!this.hasPending()) return Promise.resolve(this.loaded)
    if (this.composing || !this.loaded || this.snapshot.status === 'conflict')
      return Promise.resolve(false)
    this.operation = this.savePending().finally(() => {
      this.operation = null
    })
    return this.operation
  }

  private async savePending(): Promise<boolean> {
    if (this.version === this.savedVersion) return true
    if (!this.request)
      this.request = {
        version: this.version,
        payload: {
          data: structuredClone(this.snapshot.value),
          request_id: crypto.randomUUID(),
          expected_revision: this.snapshot.revision,
        },
      }
    const request = this.request
    this.publish({ status: 'saving', error: null })
    try {
      const result = await this.save(request.payload)
      if (this.discarded) return true
      this.savedVersion = request.version
      this.request = null
      this.publish({
        status: this.version === this.savedVersion ? 'saved' : 'unsaved',
        revision: result.revision,
        updatedAt: result.updated_at,
        error: null,
      })
      this.committed(result)
    } catch (cause) {
      if (this.discarded) return true
      const error = cause instanceof Error ? cause : new Error('Could not save this draft.')
      const conflict = error instanceof SessionHttpError && error.status === 409
      if (conflict) this.request = null
      this.publish({ status: conflict ? 'conflict' : 'error', error })
      return false
    }
    if (this.composing) return false
    // Further edits must use the revision returned by this save, so writes stay sequential.
    return this.savePending()
  }

  reload = async () => {
    if (this.operation) await this.operation
    if (this.discarded) return true
    const version = this.version
    this.publish({ status: 'loading', error: null })
    try {
      const response = await this.read()
      if (this.discarded) return true
      if (this.version !== version) {
        this.loaded = true
        this.publish({
          revision: response.revision,
          status: 'conflict',
          error: new SessionHttpError(409, 'draft_conflict'),
        })
        return false
      }
      this.request = null
      this.savedVersion = this.version
      this.loaded = false
      this.hydrate(response)
      this.committed(response)
      return true
    } catch (cause) {
      if (this.discarded) return true
      this.publish({
        status: 'error',
        error: cause instanceof Error ? cause : new Error('Could not load this draft.'),
      })
      return false
    }
  }

  retry = async () => {
    if (this.discarded) return true
    if (!this.loaded) {
      try {
        const response = await this.read()
        if (this.discarded) return true
        if (this.hasPending()) {
          this.loaded = true
          if (response.revision > 0 || Object.keys(response.data).length > 0) {
            this.publish({
              revision: response.revision,
              status: 'conflict',
              error: new SessionHttpError(409, 'draft_conflict'),
            })
            return false
          }
          this.publish({ revision: response.revision, status: 'unsaved', error: null })
        } else this.hydrate(response)
        this.committed(response)
      } catch (cause) {
        if (this.discarded) return true
        this.publish({
          status: 'error',
          error: cause instanceof Error ? cause : new Error('Could not load this draft.'),
        })
        return false
      }
    }
    return this.flush()
  }

  overwrite = async () => {
    if (this.operation) await this.operation
    if (this.discarded) return true
    try {
      const response = await this.read()
      if (this.discarded) return true
      this.loaded = true
      this.request = null
      this.publish({ revision: response.revision, status: 'unsaved', error: null })
      return await this.flush()
    } catch (cause) {
      if (this.discarded) return true
      this.publish({
        status: 'error',
        error: cause instanceof Error ? cause : new Error('Could not load this draft.'),
      })
      return false
    }
  }
}
