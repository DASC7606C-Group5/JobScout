import { Outlet, useParams } from '@tanstack/react-router'
import { useEffect, useRef, useState, useSyncExternalStore } from 'react'

import { useScout } from '../../state/scout-context'
import { useScoutSession } from '../../state/session-context'
import { useSessionHistory } from '../../state/workspace-queries'
import { Icon } from '../icon'
import { Sidebar } from './sidebar'

const sidebarPreferenceKey = 'jobscout.sidebar-expanded'

function desktopViewport() {
  return window.matchMedia('(min-width: 1024px)').matches
}

function subscribeViewport(listener: () => void) {
  const viewport = window.matchMedia('(min-width: 1024px)')
  viewport.addEventListener('change', listener)
  return () => viewport.removeEventListener('change', listener)
}

function readSidebarPreference() {
  try {
    return localStorage.getItem(sidebarPreferenceKey) === 'true'
  } catch {
    return false
  }
}

function focusDrawerTarget(sidebar: HTMLElement | null, sessionId: string | undefined) {
  const active = sessionId
    ? sidebar?.querySelector<HTMLElement>(`[data-session-id="${CSS.escape(sessionId)}"]`)
    : undefined
  const target = active ?? sidebar?.querySelector<HTMLElement>('[data-history-heading]')
  target?.focus()
  return Boolean(active) || !sessionId
}

export function WorkspaceLayout() {
  const announcement = useScout((state) => state.announcement)
  const saveError = useScout((state) => state.saveError)
  const clearSaveError = useScout((state) => state.clearSaveError)
  const currentSession = useScoutSession().session
  const history = useSessionHistory()
  const { sessionId } = useParams({ strict: false })
  const desktop = useSyncExternalStore(subscribeViewport, desktopViewport, () => false)
  const [expanded, setExpanded] = useState(readSidebarPreference)
  const [mobileOpen, setMobileOpen] = useState(false)
  const sidebar = useRef<HTMLElement>(null)
  const restoreFocus = useRef<HTMLElement | null>(null)
  const historyFocusRequested = useRef(false)
  const open = desktop ? expanded : mobileOpen

  function setDrawerOpen(next: boolean) {
    if (desktop) {
      setExpanded(next)
      try {
        localStorage.setItem(sidebarPreferenceKey, String(next))
      } catch {
        // Keep the sidebar usable when browser storage is unavailable.
      }
    } else {
      if (next) restoreFocus.current = document.activeElement as HTMLElement | null
      setMobileOpen(next)
    }
  }

  function openHistory() {
    if (open) {
      historyFocusRequested.current = !focusDrawerTarget(sidebar.current, sessionId)
    } else {
      historyFocusRequested.current = true
      setDrawerOpen(true)
    }
  }

  useEffect(() => {
    const viewport = window.matchMedia('(min-width: 1024px)')
    const resetMobileDrawer = () => setMobileOpen(false)
    viewport.addEventListener('change', resetMobileDrawer)
    return () => viewport.removeEventListener('change', resetMobileDrawer)
  }, [])

  useEffect(() => {
    if (!open || !historyFocusRequested.current) return
    const frame = requestAnimationFrame(() => {
      historyFocusRequested.current = !focusDrawerTarget(sidebar.current, sessionId)
    })
    return () => cancelAnimationFrame(frame)
  }, [open, sessionId, history.data, currentSession])

  useEffect(() => {
    if (desktop || !mobileOpen) return

    const panel = sidebar.current
    if (!panel) return
    if (!panel.contains(document.activeElement))
      panel.querySelector<HTMLElement>('[data-drawer-close]')?.focus()

    function trapKeyboard(event: KeyboardEvent) {
      if (document.querySelector('dialog[open]')) return
      if (event.key === 'Escape') {
        event.preventDefault()
        setMobileOpen(false)
        return
      }
      if (event.key !== 'Tab' || !panel) return
      const controls = Array.from(
        panel.querySelectorAll<HTMLElement>('a[href], button:not(:disabled), [tabindex="0"]'),
      ).filter(
        (element) =>
          element.getClientRects().length > 0 && getComputedStyle(element).visibility === 'visible',
      )
      const first = controls[0]
      const last = controls.at(-1)
      if (
        event.shiftKey &&
        (document.activeElement === first || !panel.contains(document.activeElement))
      ) {
        event.preventDefault()
        last?.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first?.focus()
      }
    }

    document.addEventListener('keydown', trapKeyboard)
    return () => {
      document.removeEventListener('keydown', trapKeyboard)
      const trigger = restoreFocus.current
      if (trigger?.isConnected && trigger.getClientRects().length > 0) trigger.focus()
    }
  }, [desktop, mobileOpen])

  return (
    <div className="drawer min-h-screen bg-base-200/25 text-base-content lg:drawer-open">
      <input
        id="workspace-drawer"
        type="checkbox"
        className="drawer-toggle"
        checked={open}
        tabIndex={-1}
        aria-hidden="true"
        onChange={(event) => setDrawerOpen(event.target.checked)}
      />
      <div className="drawer-content min-w-0" inert={!desktop && mobileOpen ? true : undefined}>
        <a
          href="#main-content"
          className="sr-only z-50 rounded-field bg-base-content p-3 text-base-100 focus:not-sr-only focus:fixed focus:top-3 focus:left-3"
        >
          Skip to main content
        </a>
        <button
          id="workspace-drawer-trigger"
          type="button"
          className="btn fixed top-3 left-3 z-30 btn-square border-base-300 bg-base-100 drawer-button btn-sm lg:hidden"
          aria-label={open ? 'Close sidebar' : 'Open sidebar'}
          aria-expanded={open}
          aria-controls="workspace-sidebar"
          onClick={() => setDrawerOpen(!open)}
        >
          <Icon name="panel" size={19} />
        </button>
        <main
          id="main-content"
          tabIndex={-1}
          className="mx-auto max-w-7xl px-5 pt-20 pb-10 sm:px-8 lg:pt-10 xl:px-12"
        >
          {saveError && (
            <div className="mb-5 alert alert-error sm:alert-horizontal" role="alert">
              <Icon name="info" size={18} />
              <span>{saveError}</span>
              <button type="button" className="btn btn-ghost btn-sm" onClick={clearSaveError}>
                Dismiss
              </button>
            </div>
          )}
          <Outlet />
        </main>
        <div className="sr-only" aria-live="polite">
          {announcement}
        </div>
      </div>
      <Sidebar
        ref={sidebar}
        sessionId={sessionId}
        expanded={open}
        mobile={!desktop}
        onHistory={openHistory}
        onToggleDrawer={() => setDrawerOpen(!open)}
        onNavigate={() => {
          if (!desktop) setMobileOpen(false)
        }}
      />
    </div>
  )
}
