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
        aria-label="JobScout home"
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
          Explore
        </p>
        <nav aria-label="Main navigation" className="flex gap-1 md:flex-col md:gap-2">
          <Link
            to="/"
            activeOptions={{ exact: true }}
            aria-label="Explore opportunities"
            aria-current={!savedView ? 'page' : undefined}
            className={`flex items-center gap-3 rounded-xl px-3 py-3 text-sm transition-colors disabled:opacity-50 ${!savedView ? 'bg-primary/20 font-semibold text-primary-content' : 'text-base-content/60 hover:bg-base-200/50'}`}
          >
            <Icon name="compass" size={19} />
            <span className="hidden sm:inline">Explore</span>
          </Link>
          <Link
            to="/saved"
            aria-label={`Saved jobs, ${savedCount}`}
            aria-current={savedView ? 'page' : undefined}
            className={`flex items-center gap-3 rounded-xl px-3 py-3 text-sm transition-colors disabled:opacity-50 ${savedView ? 'bg-secondary/45 font-semibold' : 'text-base-content/60 hover:bg-base-200/50'}`}
          >
            <Icon name="bookmark" size={19} />
            <span className="hidden sm:inline">Saved jobs</span>
            <span className="ml-auto rounded-md bg-base-200 px-1.5 py-0.5 text-[10px] tabular-nums">
              {savedCount}
            </span>
          </Link>
        </nav>
      </div>
      <div className="mt-auto hidden md:block">
        <div className="rounded-xl border border-base-300 bg-base-200/25 p-4">
          <Icon name="leaf" size={22} className="text-primary-content" />
          <p className="mt-3 text-xs font-semibold">A good job should be right for you.</p>
          <p className="mt-2 text-[11px] leading-5 text-base-content/55">
            Less applying to everything,
            <br />
            more focused exploration.
          </p>
        </div>
        <div className="mt-6 flex items-center gap-2.5 border-t border-base-300 pt-5">
          <span className="flex size-8 items-center justify-center rounded-full bg-secondary/40 text-xs font-semibold">
            Me
          </span>
          <div>
            <p className="text-xs font-medium">My workspace</p>
          </div>
        </div>
      </div>
    </aside>
  )
}
