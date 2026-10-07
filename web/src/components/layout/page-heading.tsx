import type { ReactNode } from 'react'

export function PageHeading({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
      <div className="min-w-0">
        <h1
          tabIndex={-1}
          className="text-2xl font-semibold tracking-tight outline-none sm:text-[28px] sm:leading-snug"
        >
          {title}
        </h1>
      </div>
      {children}
    </div>
  )
}
