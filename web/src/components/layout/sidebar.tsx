import { Link, useMatchRoute } from '@tanstack/react-router'

import { useScout } from '../../state/scout-context'
import { Icon } from '../icon'

export function Sidebar() {
  const savedCount = useScout((state) => state.saved.length)
  const matchRoute = useMatchRoute()
  const savedView = Boolean(matchRoute({ to: '/saved' }))
  return (
    <aside className="flex border-b border-base-300 bg-base-100 px-4 py-4 md:sticky md:top-0 md:h-screen md:flex-col md:border-r md:border-b-0 md:px-5 md:py-8">
      <Link
        to="/"
        className="flex shrink-0 items-center gap-2.5 self-start rounded-md md:px-1"
        aria-label="JobScout 首页"
      >
        <span className="flex size-9 items-center justify-center rounded-xl bg-primary/55 text-primary-content">
          <Icon name="compass" size={24} />
        </span>
        <span className="text-xl font-bold tracking-tight">
          JobScout<span className="text-primary-content">.</span>
        </span>
      </Link>
      <div className="ml-auto md:mt-12 md:ml-0">
        <p className="mb-3 hidden px-3 text-[10px] font-semibold tracking-[0.15em] text-base-content/40 md:block">
          我的求职空间
        </p>
        <nav aria-label="主导航" className="flex gap-1 md:flex-col md:gap-2">
          <Link
            to="/"
            activeOptions={{ exact: true }}
            aria-label="发现机会"
            aria-current={!savedView ? 'page' : undefined}
            className={`flex items-center gap-3 rounded-xl px-3 py-3 text-sm transition-colors disabled:opacity-50 ${!savedView ? 'bg-primary/20 font-semibold text-primary-content' : 'text-base-content/60 hover:bg-base-200/50'}`}
          >
            <Icon name="compass" size={19} />
            <span className="hidden sm:inline">发现机会</span>
          </Link>
          <Link
            to="/saved"
            aria-label={`收藏岗位，${savedCount} 个`}
            aria-current={savedView ? 'page' : undefined}
            className={`flex items-center gap-3 rounded-xl px-3 py-3 text-sm transition-colors disabled:opacity-50 ${savedView ? 'bg-secondary/45 font-semibold' : 'text-base-content/60 hover:bg-base-200/50'}`}
          >
            <Icon name="bookmark" size={19} />
            <span className="hidden sm:inline">收藏岗位</span>
            <span className="ml-auto rounded-md bg-base-200 px-1.5 py-0.5 text-[10px] tabular-nums">
              {savedCount}
            </span>
          </Link>
        </nav>
      </div>
      <div className="mt-auto hidden md:block">
        <div className="rounded-xl border border-base-300 bg-base-200/25 p-4">
          <Icon name="leaf" size={22} className="text-primary-content" />
          <p className="mt-3 text-xs font-semibold">好工作，也要适合你。</p>
          <p className="mt-2 text-[11px] leading-5 text-base-content/55">
            少一点海投，
            <br />
            多一点有方向的探索。
          </p>
        </div>
        <div className="mt-6 flex items-center gap-2.5 border-t border-base-300 pt-5">
          <span className="flex size-8 items-center justify-center rounded-full bg-secondary/40 text-xs font-semibold">
            我
          </span>
          <div>
            <p className="text-xs font-medium">我的工作空间</p>
            <p className="mt-1 text-[10px] text-base-content/45">本地体验 · 无需登录</p>
          </div>
        </div>
      </div>
    </aside>
  )
}
