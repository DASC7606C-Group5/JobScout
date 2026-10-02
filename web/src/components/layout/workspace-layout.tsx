import { Outlet } from '@tanstack/react-router'

import { useScout } from '../../state/scout-context'
import { Sidebar } from './sidebar'
import { WorkspaceHeader } from './workspace-header'

export function WorkspaceLayout() {
  const announcement = useScout((state) => state.announcement)
  return (
    <div className="min-h-screen bg-base-200/25 text-base-content md:grid md:grid-cols-[216px_minmax(0,1fr)]">
      <a
        href="#main-content"
        className="sr-only z-50 rounded-lg bg-base-content p-3 text-base-100 focus:not-sr-only focus:fixed focus:top-3 focus:left-3"
      >
        跳转到主要内容
      </a>
      <Sidebar />
      <div className="min-w-0">
        <WorkspaceHeader />
        <main
          id="main-content"
          className="mx-auto max-w-7xl px-5 pt-8 pb-10 sm:px-8 sm:pt-10 xl:px-12"
        >
          <Outlet />
          <footer className="mt-9 flex flex-wrap items-center justify-between gap-2 border-t border-base-300 pt-5 text-[10px] text-base-content/45">
            <span>JobScout · 为你的下一步，找一点方向。</span>
            <span>示例体验 · 所有岗位均为虚构数据</span>
          </footer>
        </main>
      </div>
      <div className="sr-only" aria-live="polite">
        {announcement}
      </div>
    </div>
  )
}
