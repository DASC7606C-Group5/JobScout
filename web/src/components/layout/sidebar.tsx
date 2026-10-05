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
  const [historyVisible, setHistoryVisible] = useState(true)
  const savedCount = saved.data?.length ?? 0
  const historyExpanded = expanded && historyVisible
  const drawerAction = mobile ? 'Close sidebar' : expanded ? 'Collapse sidebar' : 'Expand sidebar'

  function toggleHistory() {
    if (!expanded) {
      setHistoryVisible(true)
      onHistory()
    } else setHistoryVisible((visible) => !visible)
  }

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
        className="flex h-dvh min-h-full flex-col border-r border-base-300 bg-base-100 motion-safe:transition-[width] motion-safe:duration-200 motion-safe:ease-out is-drawer-close:w-18 is-drawer-open:w-72 is-drawer-open:overflow-hidden"
      >
        <div className="flex h-24 shrink-0 items-center gap-2 px-3">
          <Link
            to="/new"
            search={{}}
            onClick={beforeNavigate}
            className="flex min-w-0 items-center gap-3 rounded-field is-drawer-close:tooltip is-drawer-close:tooltip-right"
            data-tip="New search"
            aria-label="JobScout — New search"
          >
            <span className="flex size-11 shrink-0 items-center justify-center">
              <span className="flex size-9 items-center justify-center rounded-box bg-primary/55 text-primary-content">
                <Icon name="compass" size={24} />
              </span>
            </span>
            <span className="text-xl font-bold tracking-tight whitespace-nowrap is-drawer-close:hidden">
              JobScout<span className="text-primary-content">.</span>
            </span>
          </Link>
          <button
            type="button"
            data-drawer-close
            className="btn ml-auto btn-square size-11 shrink-0 btn-ghost shadow-none drawer-button lg:hidden"
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
        />
        <div className="mx-3 mt-5 shrink-0 border-t border-base-300 pt-4">
          <div
            className="is-drawer-close:tooltip is-drawer-close:tooltip-right"
            data-tip="Search history"
          >
            <button
              type="button"
              className={`btn h-11 w-full flex-nowrap justify-start gap-3 border-0 btn-ghost p-0 text-sm font-medium shadow-none ${sessionId && !expanded ? 'bg-primary/15 text-primary-content' : 'text-base-content/70'}`}
              aria-label="Search history"
              aria-controls="search-history"
              aria-expanded={historyExpanded}
              onClick={toggleHistory}
            >
              <span className="flex size-11 shrink-0 items-center justify-center">
                <Icon name="clock" size={20} />
              </span>
              <span className="whitespace-nowrap is-drawer-close:hidden">Search history</span>
              <Icon
                name="chevron"
                size={14}
                className={`mr-3 ml-auto shrink-0 is-drawer-close:hidden ${historyExpanded ? 'rotate-90' : ''}`}
              />
            </button>
          </div>
        </div>
        <HistoryMenu
          hidden={!historyExpanded}
          sessionId={sessionId}
          beforeNavigate={beforeNavigate}
          historyHeading={historyHeading}
          onDelete={openDelete}
        />
        <div className="mt-auto flex h-20 shrink-0 items-center gap-3 border-t border-base-300 px-3">
          <div
            className="shrink-0 is-drawer-close:tooltip is-drawer-close:tooltip-right"
            data-tip={drawerAction}
          >
            <button
              id="workspace-sidebar-toggle"
              type="button"
              className="btn btn-square size-11 btn-ghost shadow-none drawer-button"
              aria-label={drawerAction}
              aria-expanded={expanded}
              aria-controls="workspace-sidebar"
              onClick={onToggleDrawer}
            >
              <Icon name="panel" size={20} className="is-drawer-open:rotate-180" />
            </button>
          </div>
          <label
            htmlFor="workspace-sidebar-toggle"
            className="cursor-pointer text-xs whitespace-nowrap text-base-content/60 hover:text-base-content is-drawer-close:hidden"
          >
            {drawerAction}
          </label>
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
}: {
  pathname: string
  savedCount: number
  beforeNavigate: NavigateHandler
}) {
  return (
    <nav aria-label="Main navigation" className="shrink-0">
      <ul className="menu w-full gap-2 menu-sm px-3 py-0">
        <li
          className="w-full is-drawer-close:tooltip is-drawer-close:tooltip-right"
          data-tip="New search"
        >
          <Link
            to="/new"
            search={{}}
            onClick={beforeNavigate}
            className={`flex h-11 w-full flex-nowrap items-center gap-3 p-0 text-sm leading-normal shadow-none ${pathname === '/new' ? 'bg-primary/20 font-semibold text-primary-content' : 'text-base-content/75'}`}
            aria-label="New search"
            aria-current={pathname === '/new' ? 'page' : undefined}
          >
            <span className="flex size-11 shrink-0 items-center justify-center">
              <Icon name="plus" size={20} />
            </span>
            <span className="whitespace-nowrap is-drawer-close:hidden">New search</span>
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
            className={`flex h-11 w-full flex-nowrap items-center gap-3 p-0 text-sm leading-normal shadow-none ${pathname === '/saved' ? 'bg-primary/20 font-semibold text-primary-content' : 'text-base-content/75'}`}
            aria-label="Saved jobs"
            aria-current={pathname === '/saved' ? 'page' : undefined}
          >
            <span className="flex size-11 shrink-0 items-center justify-center">
              <Icon name="bookmark" size={20} />
            </span>
            <span className="whitespace-nowrap is-drawer-close:hidden">Saved jobs</span>
            <span className="mr-3 ml-auto badge border-0 bg-base-200 badge-sm tabular-nums is-drawer-close:hidden">
              {savedCount}
            </span>
          </Link>
        </li>
      </ul>
    </nav>
  )
}

function HistoryMenu({
  hidden,
  sessionId,
  beforeNavigate,
  historyHeading,
  onDelete,
}: {
  hidden: boolean
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
      hidden={hidden}
      aria-labelledby="search-history-heading"
      className="min-h-0 flex-1 [scrollbar-gutter:stable] overflow-y-auto px-3 pt-3 pb-5 is-drawer-close:hidden"
    >
      {current && (
        <div className="mb-4">
          <h2 className="px-3 text-[11px] font-semibold text-base-content/55">Current search</h2>
          <ul className="mt-2 flex w-full flex-col gap-2">
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
        className="px-3 text-[11px] font-medium text-base-content/50"
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
        <div className="px-3 py-5 text-xs leading-5 text-base-content/60">
          <p className="font-medium text-base-content/75">A place to pick up where you left off.</p>
          <p className="mt-1">Start a search and find it here next time.</p>
        </div>
      )}
      <ul className="mt-2 flex w-full flex-col gap-2">
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
      className={`group card border transition-colors ${sessionId === search.session_id ? 'border-primary/30 bg-primary/10' : 'border-transparent focus-within:bg-base-200/60 hover:bg-base-200/60'}`}
    >
      <div className="flex min-w-0 items-start">
        <Link
          to="/searches/$sessionId"
          params={{ sessionId: search.session_id }}
          search={{}}
          onClick={beforeNavigate}
          data-session-id={search.session_id}
          aria-current={sessionId === search.session_id ? 'page' : undefined}
          className="flex min-w-0 flex-1 flex-col items-start gap-1.5 rounded-box px-3 py-3"
        >
          <span className="line-clamp-2 text-xs leading-5 font-medium">{search.title}</span>
          {search.location && (
            <span className="text-[11px] text-base-content/60">{search.location}</span>
          )}
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
          className="btn mt-2 mr-1 btn-square shrink-0 btn-ghost text-base-content/45 shadow-none btn-xs hover:text-error"
          aria-label={`Delete search: ${title}`}
          onClick={(event) => onDelete(search, event.currentTarget)}
        >
          <Icon name="trash" size={15} />
        </button>
      </div>
    </li>
  )
}
