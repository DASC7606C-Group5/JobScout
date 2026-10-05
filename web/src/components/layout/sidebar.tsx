import { Link, useNavigate, useRouter, useRouterState } from '@tanstack/react-router'
import { useRef, useState, type MouseEvent, type Ref, type RefObject } from 'react'

import { applicantErrorMessage } from '../../lib/applicant-errors'
import type { SessionSummary } from '../../lib/contracts'
import { SessionHttpError } from '../../lib/session-client'
import { flushPendingDrafts } from '../../state/draft-navigation'
import { useScoutSession } from '../../state/session-context'
import { useDeleteSession, useSavedJobs, useSessionHistory } from '../../state/workspace-queries'
import { Icon } from '../icon'

type HistorySearch = Pick<SessionSummary, 'session_id' | 'title' | 'location' | 'outcome'> & {
  updated_at?: string
}

function searchTitle(search: HistorySearch) {
  return search.location ? `${search.title} · ${search.location}` : search.title
}

function searchStatus(search: HistorySearch) {
  if (search.outcome === 'running') return { label: 'Searching', tone: 'status-info' }
  if (search.outcome === 'completed') return { label: 'Complete', tone: 'status-success' }
  if (search.outcome === 'failed') return { label: 'Needs attention', tone: 'status-warning' }
  return { label: 'Waiting for you', tone: 'status-neutral' }
}

const historyDate = new Intl.DateTimeFormat('en-HK', {
  month: 'short',
  day: 'numeric',
  timeZone: 'Asia/Hong_Kong',
})
const historyTimestamp = new Intl.DateTimeFormat('en-HK', {
  dateStyle: 'medium',
  timeStyle: 'short',
  timeZone: 'Asia/Hong_Kong',
})

export function Sidebar({
  ref,
  sessionId,
  expanded,
  mobile,
  onHistory,
  onToggleDrawer,
  onNavigate,
}: {
  ref: Ref<HTMLElement>
  sessionId: string | undefined
  expanded: boolean
  mobile: boolean
  onHistory: () => void
  onToggleDrawer: () => void
  onNavigate: () => void
}) {
  const pathname = useRouterState({ select: (state) => state.location.pathname })
  const saved = useSavedJobs()
  const deletion = useDeleteSession()
  const navigate = useNavigate()
  const router = useRouter()
  const dialog = useRef<HTMLDialogElement>(null)
  const cancel = useRef<HTMLButtonElement>(null)
  const deleteTrigger = useRef<HTMLButtonElement | null>(null)
  const deleteConfirmed = useRef(false)
  const historyHeading = useRef<HTMLHeadingElement>(null)
  const [candidate, setCandidate] = useState<HistorySearch | null>(null)
  const [announcement, setAnnouncement] = useState('')
  const savedCount = saved.data?.length ?? 0
  const drawerAction = mobile ? 'Close sidebar' : expanded ? 'Collapse sidebar' : 'Expand sidebar'

  function beforeNavigate(event: MouseEvent<HTMLAnchorElement>) {
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0)
      return
    event.preventDefault()
    const target = new URL(event.currentTarget.href)
    const href = `${target.pathname}${target.search}${target.hash}`
    void (async () => {
      if (!(await flushPendingDrafts())) return
      onNavigate()
      await navigate({ href })
    })()
  }

  function openDelete(search: HistorySearch, trigger: HTMLButtonElement) {
    deleteTrigger.current = trigger
    deletion.reset()
    setCandidate(search)
    dialog.current?.showModal()
    cancel.current?.focus()
  }

  function closeDelete() {
    setCandidate(null)
    deletion.reset()
    if (deleteConfirmed.current) {
      deleteConfirmed.current = false
      historyHeading.current?.focus()
    } else if (deleteTrigger.current?.isConnected) deleteTrigger.current.focus()
    else historyHeading.current?.focus()
  }

  async function confirmDelete() {
    if (!candidate || deletion.isPending) return
    const deletedId = candidate.session_id
    try {
      await deletion.mutateAsync(deletedId)
      deleteConfirmed.current = true
      setAnnouncement('Search deleted. Your saved jobs and new search draft are still available.')
      dialog.current?.close()
      if (router.state.location.pathname === `/searches/${encodeURIComponent(deletedId)}`) {
        onNavigate()
        await navigate({ to: '/new', search: {} })
      }
    } catch {
      // The query mutation preserves the error for retry in this dialog.
    }
  }

  return (
    <div className="drawer-side z-40 lg:z-10 is-drawer-close:overflow-visible">
      <label htmlFor="workspace-drawer" aria-label="Close sidebar" className="drawer-overlay" />
      <aside
        id="workspace-sidebar"
        ref={ref}
        role={mobile && expanded ? 'dialog' : undefined}
        aria-modal={mobile && expanded ? true : undefined}
        aria-label="Workspace navigation"
        className="flex h-dvh min-h-full flex-col border-r border-base-300 bg-base-100 is-drawer-close:w-14 is-drawer-open:w-64"
      >
        <div className="flex h-20 shrink-0 items-center px-2 is-drawer-close:justify-center is-drawer-open:px-4">
          <Link
            to="/new"
            search={{}}
            onClick={beforeNavigate}
            className="flex min-w-0 items-center gap-2.5 rounded-md is-drawer-close:tooltip is-drawer-close:tooltip-right"
            data-tip="New search"
            aria-label="JobScout — New search"
          >
            <span className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-primary/55 text-primary-content">
              <Icon name="compass" size={24} />
            </span>
            <span className="text-xl font-bold tracking-tight is-drawer-close:hidden">
              JobScout<span className="text-primary-content">.</span>
            </span>
          </Link>
          <button
            type="button"
            data-drawer-close
            className="btn ml-auto btn-square btn-ghost drawer-button btn-sm lg:hidden"
            aria-label="Close sidebar"
            aria-controls="workspace-sidebar"
            aria-expanded={expanded}
            onClick={onToggleDrawer}
          >
            <Icon name="close" size={18} />
          </button>
        </div>
        <SidebarNavigation
          pathname={pathname}
          savedCount={savedCount}
          beforeNavigate={beforeNavigate}
          onHistory={onHistory}
          expanded={expanded}
        />
        <HistoryMenu
          sessionId={sessionId}
          beforeNavigate={beforeNavigate}
          historyHeading={historyHeading}
          onDelete={openDelete}
        />
        <div
          className="mt-auto shrink-0 border-t border-base-300 p-2 is-drawer-close:tooltip is-drawer-close:tooltip-right"
          data-tip={drawerAction}
        >
          <button
            type="button"
            className="btn h-10 w-full justify-start gap-3 border-0 btn-ghost px-3 leading-normal drawer-button btn-sm is-drawer-close:justify-center is-drawer-close:px-0"
            aria-label={drawerAction}
            aria-expanded={expanded}
            aria-controls="workspace-sidebar"
            onClick={onToggleDrawer}
          >
            <Icon name="panel" size={20} className="shrink-0 is-drawer-open:rotate-180" />
            <span className="text-xs font-normal is-drawer-close:hidden">{drawerAction}</span>
          </button>
        </div>
        <div className="sr-only" aria-live="polite">
          {announcement}
        </div>
        <DeleteSearchDialog
          dialog={dialog}
          cancel={cancel}
          candidate={candidate}
          deletion={deletion}
          onClose={closeDelete}
          onConfirm={() => void confirmDelete()}
        />
      </aside>
    </div>
  )
}

type NavigateHandler = (event: MouseEvent<HTMLAnchorElement>) => void

function SidebarNavigation({
  pathname,
  savedCount,
  beforeNavigate,
  onHistory,
  expanded,
}: {
  pathname: string
  savedCount: number
  beforeNavigate: NavigateHandler
  onHistory: () => void
  expanded: boolean
}) {
  return (
    <nav aria-label="Main navigation" className="shrink-0">
      <ul className="menu w-full gap-1 menu-sm px-2 py-3">
        <li
          className="w-full is-drawer-close:tooltip is-drawer-close:tooltip-right"
          data-tip="New search"
        >
          <Link
            to="/new"
            search={{}}
            onClick={beforeNavigate}
            className={`flex h-10 w-full items-center gap-3 px-3 leading-normal is-drawer-close:justify-center is-drawer-close:px-0 ${pathname === '/new' ? 'menu-active' : ''}`}
            aria-label="New search"
            aria-current={pathname === '/new' ? 'page' : undefined}
          >
            <Icon name="plus" size={20} className="shrink-0" />
            <span className="is-drawer-close:hidden">New search</span>
          </Link>
        </li>
        <li
          className="w-full is-drawer-close:tooltip is-drawer-close:tooltip-right"
          data-tip="Saved jobs"
        >
          <Link
            to="/saved"
            search={{}}
            onClick={beforeNavigate}
            className={`flex h-10 w-full items-center gap-3 px-3 leading-normal is-drawer-close:justify-center is-drawer-close:px-0 ${pathname === '/saved' ? 'menu-active' : ''}`}
            aria-label="Saved jobs"
            aria-current={pathname === '/saved' ? 'page' : undefined}
          >
            <Icon name="bookmark" size={20} className="shrink-0" />
            <span className="is-drawer-close:hidden">Saved jobs</span>
            <span className="ml-auto badge badge-sm tabular-nums is-drawer-close:hidden">
              {savedCount}
            </span>
          </Link>
        </li>
        <li
          className="w-full is-drawer-close:tooltip is-drawer-close:tooltip-right is-drawer-open:hidden"
          data-tip="Search history"
        >
          <button
            type="button"
            className="flex h-10 w-full items-center gap-3 px-3 leading-normal is-drawer-close:justify-center is-drawer-close:px-0"
            aria-label="Search history"
            aria-controls="search-history"
            aria-expanded={expanded}
            onClick={onHistory}
          >
            <Icon name="clock" size={20} className="shrink-0" />
            <span className="is-drawer-close:hidden">Search history</span>
          </button>
        </li>
      </ul>
    </nav>
  )
}

function HistoryMenu({
  sessionId,
  beforeNavigate,
  historyHeading,
  onDelete,
}: {
  sessionId: string | undefined
  beforeNavigate: NavigateHandler
  historyHeading: Ref<HTMLHeadingElement>
  onDelete: (search: HistorySearch, trigger: HTMLButtonElement) => void
}) {
  const history = useSessionHistory()
  const { session } = useScoutSession()
  const searches = history.data?.pages.flatMap((page) => page.items) ?? []
  const current =
    session &&
    session.session_id === sessionId &&
    !searches.some((search) => search.session_id === sessionId)
      ? {
          session_id: session.session_id,
          title: session.profile?.target_directions.join(', ') || 'Search',
          location: session.profile?.preferences.location || '',
          outcome: session.outcome,
        }
      : null
  return (
    <section
      id="search-history"
      aria-labelledby="search-history-heading"
      className="min-h-0 flex-1 overflow-y-auto border-t border-base-300 px-2 pt-4 pb-3 is-drawer-close:hidden"
    >
      {current && (
        <div className="mb-4">
          <h2 className="px-3 text-[11px] font-semibold text-base-content/55">Current search</h2>
          <ul className="menu mt-2 w-full menu-sm p-0">
            <HistoryRow
              search={current}
              sessionId={sessionId}
              beforeNavigate={beforeNavigate}
              onDelete={onDelete}
            />
          </ul>
        </div>
      )}
      <h2
        id="search-history-heading"
        ref={historyHeading}
        tabIndex={-1}
        data-history-heading
        className="px-3 text-[11px] font-semibold text-base-content/55"
      >
        Recent searches
      </h2>
      {history.isPending && (
        <output className="flex min-h-20 items-center gap-2 px-3 text-xs text-base-content/65">
          <span className="loading loading-xs loading-spinner" aria-hidden="true" />
          Loading searches
        </output>
      )}
      {!history.isPending && searches.length === 0 && !history.isError && (
        <p className="px-3 py-5 text-xs leading-5 text-base-content/65">
          Your searches will appear here after you start one.
        </p>
      )}
      <ul className="menu mt-2 w-full gap-1 menu-sm p-0">
        {searches.map((search) => (
          <HistoryRow
            key={search.session_id}
            search={search}
            sessionId={sessionId}
            beforeNavigate={beforeNavigate}
            onDelete={onDelete}
          />
        ))}
      </ul>
      {history.isError && (
        <div role="alert" className="px-3 py-4 text-xs">
          <p className="text-error">Could not load your search history.</p>
          <button
            type="button"
            className="btn mt-2 btn-ghost btn-xs"
            onClick={() => void history.refetch()}
          >
            Try again
          </button>
        </div>
      )}
      {history.hasNextPage && (
        <button
          type="button"
          className="btn mt-3 w-full btn-ghost btn-sm"
          disabled={history.isFetchingNextPage}
          onClick={() => void history.fetchNextPage()}
        >
          {history.isFetchingNextPage && (
            <span className="loading loading-xs loading-spinner" aria-hidden="true" />
          )}
          Load more
        </button>
      )}
    </section>
  )
}

function DeleteSearchDialog({
  dialog,
  cancel,
  candidate,
  deletion,
  onClose,
  onConfirm,
}: {
  dialog: RefObject<HTMLDialogElement | null>
  cancel: RefObject<HTMLButtonElement | null>
  candidate: HistorySearch | null
  deletion: ReturnType<typeof useDeleteSession>
  onClose: () => void
  onConfirm: () => void
}) {
  return (
    <dialog
      ref={dialog}
      className="modal"
      aria-labelledby="delete-search-title"
      aria-describedby="delete-search-consequence"
      onCancel={(event) => {
        if (deletion.isPending) event.preventDefault()
      }}
      onClose={onClose}
    >
      <div className="modal-box">
        <h2 id="delete-search-title" className="text-lg font-semibold">
          Delete search?
        </h2>
        <p className="mt-3 text-sm font-medium">{candidate ? searchTitle(candidate) : ''}</p>
        <p id="delete-search-consequence" className="mt-2 text-sm leading-6 text-base-content/70">
          This permanently removes this search, its conversation, results and unfinished answers.
          Your saved jobs and new search draft will stay.
        </p>
        {deletion.error && (
          <p role="alert" className="mt-4 text-sm text-error">
            {deletion.error instanceof SessionHttpError
              ? applicantErrorMessage(deletion.error.code, deletion.error.status)
              : applicantErrorMessage('connection_unavailable')}
          </p>
        )}
        <form method="dialog" className="modal-action" noValidate>
          <button
            type="submit"
            ref={cancel}
            className="btn btn-ghost"
            disabled={deletion.isPending}
          >
            Keep search
          </button>
          <button
            type="button"
            className="btn btn-error"
            disabled={deletion.isPending}
            onClick={onConfirm}
          >
            {deletion.isPending && (
              <span className="loading loading-xs loading-spinner" aria-hidden="true" />
            )}
            Delete search
          </button>
        </form>
      </div>
    </dialog>
  )
}

function HistoryRow({
  search,
  sessionId,
  beforeNavigate,
  onDelete,
}: {
  search: HistorySearch
  sessionId: string | undefined
  beforeNavigate: NavigateHandler
  onDelete: (search: HistorySearch, trigger: HTMLButtonElement) => void
}) {
  const status = searchStatus(search)
  const title = searchTitle(search)
  return (
    <li
      className={`rounded-lg ${sessionId === search.session_id ? 'bg-primary/20 font-semibold focus-within:bg-primary/25 hover:bg-primary/25' : 'focus-within:bg-base-200 hover:bg-base-200'}`}
    >
      <div className="flex min-w-0 items-stretch gap-0 rounded-lg p-0 hover:bg-transparent">
        <Link
          to="/searches/$sessionId"
          params={{ sessionId: search.session_id }}
          search={{}}
          onClick={beforeNavigate}
          data-session-id={search.session_id}
          aria-current={sessionId === search.session_id ? 'page' : undefined}
          className="flex min-w-0 flex-1 flex-col items-start gap-1 rounded-lg bg-transparent px-3 py-2.5 hover:bg-transparent active:bg-transparent"
        >
          <span className="line-clamp-2 text-xs leading-5">{title}</span>
          <span className="flex w-full items-center gap-1.5 text-[10px] font-normal text-base-content/65">
            <span className={`status status-xs ${status.tone}`} aria-hidden="true" />
            <span>{status.label}</span>
            {search.updated_at && (
              <time
                dateTime={search.updated_at}
                title={`${historyTimestamp.format(new Date(search.updated_at))} HKT`}
                className="ml-auto shrink-0 tabular-nums"
              >
                {historyDate.format(new Date(search.updated_at))}
                <span className="sr-only">
                  {`, last updated ${historyTimestamp.format(new Date(search.updated_at))} HKT`}
                </span>
              </time>
            )}
          </span>
        </Link>
        <button
          type="button"
          className="btn my-auto btn-square shrink-0 bg-transparent btn-ghost text-base-content/55 btn-xs hover:bg-transparent hover:text-error active:bg-transparent"
          aria-label={`Delete search: ${title}`}
          onClick={(event) => onDelete(search, event.currentTarget)}
        >
          <Icon name="trash" size={15} />
        </button>
      </div>
    </li>
  )
}
