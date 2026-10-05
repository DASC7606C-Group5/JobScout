import { useEffect, useRef, type ReactNode } from 'react'

export function PageHeading({
  eyebrow,
  title,
  description,
  children,
}: {
  eyebrow: string
  title: string
  description: string
  children?: ReactNode
}) {
  const headingRef = useRef<HTMLHeadingElement>(null)
  useEffect(() => {
    headingRef.current?.focus()
  }, [title])
  return (
    <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
      <div>
        <p className="mb-3 text-[10px] font-bold tracking-[0.2em] text-primary-content">
          {eyebrow}
        </p>
        <h1
          ref={headingRef}
          tabIndex={-1}
          className="text-2xl font-semibold tracking-tight outline-none sm:text-[32px] sm:leading-snug"
        >
          {title}
        </h1>
        {description && (
          <p className="mt-3 text-sm leading-6 text-base-content/60">{description}</p>
        )}
      </div>
      {children}
    </div>
  )
}
