import { useLayoutEffect, useRef, type ReactNode } from 'react'

export function StepTransition({ step, children }: { step: string; children: ReactNode }) {
  const content = useRef<HTMLDivElement>(null)
  const previousStep = useRef(step)

  useLayoutEffect(() => {
    if (previousStep.current === step) return
    previousStep.current = step
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return

    const animation = content.current?.animate(
      { opacity: [0, 1] },
      { duration: 160, easing: 'ease-out' },
    )
    return () => animation?.cancel()
  }, [step])

  return <div ref={content}>{children}</div>
}
