import { useEffect, useRef, useState, type ComponentProps, type MouseEvent } from 'react'

async function settleAction(action: () => unknown, finish: () => void) {
  try {
    await action()
  } finally {
    finish()
  }
}

export function AsyncButton({
  onClick,
  children,
  disabled,
  pending = false,
  ...props
}: Omit<ComponentProps<'button'>, 'onClick'> & {
  onClick?: (event: MouseEvent<HTMLButtonElement>) => unknown
  pending?: boolean
}) {
  const [waiting, setWaiting] = useState(false)
  const locked = useRef(false)
  const mounted = useRef(true)
  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])
  async function run(event: MouseEvent<HTMLButtonElement>) {
    if (locked.current || pending || disabled) return
    locked.current = true
    setWaiting(true)
    await settleAction(
      () => onClick?.(event),
      () => {
        locked.current = false
        if (mounted.current) setWaiting(false)
      },
    )
  }
  return (
    <button
      {...props}
      disabled={disabled || pending || waiting}
      aria-busy={pending || waiting}
      onClick={(event) => {
        void run(event)
      }}
    >
      <PendingSpinner pending={pending || waiting} />
      {children}
    </button>
  )
}

export function PendingSpinner({ pending }: { pending: boolean }) {
  return pending ? <span className="loading loading-xs loading-spinner" aria-hidden="true" /> : null
}
