import type { CSSProperties } from 'react'

const paths = {
  compass: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="m16 8-2.5 5.5L8 16l2.5-5.5L16 8Z" />
    </>
  ),
  search: (
    <>
      <circle cx="10.5" cy="10.5" r="6.5" />
      <path d="m16 16 4 4" />
    </>
  ),
  bookmark: <path d="M6 4h12v17l-6-4-6 4V4Z" />,
  plus: <path d="M12 5v14M5 12h14" />,
  panel: (
    <>
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <path d="M9 4v16m5-11 3 3-3 3" />
    </>
  ),
  trash: (
    <>
      <path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7m4-7v7" />
    </>
  ),
  arrow: <path d="M4 12h16m-6-6 6 6-6 6" />,
  upload: (
    <>
      <path d="M12 16V3m-5 5 5-5 5 5M4 16v5h16v-5" />
    </>
  ),
  file: (
    <>
      <path d="M14 3H6v18h12V7l-4-4Zm0 0v5h4M9 12h6m-6 4h6" />
    </>
  ),
  pin: (
    <>
      <path d="M19 10c0 5-7 11-7 11S5 15 5 10a7 7 0 1 1 14 0Z" />
      <circle cx="12" cy="10" r="2" />
    </>
  ),
  briefcase: (
    <>
      <rect x="3" y="7" width="18" height="14" rx="2" />
      <path d="M8 7V3h8v4M3 12a22 22 0 0 0 18 0M12 11v4" />
    </>
  ),
  sparkles: (
    <>
      <path d="m12 3 2.3 6.7L21 12l-6.7 2.3L12 21l-2.3-6.7L3 12l6.7-2.3L12 3ZM20 2v4m-2-2h4" />
    </>
  ),
  check: <path d="m5 12 4 4L19 6" />,
  close: <path d="m6 6 12 12M6 18 18 6" />,
  external: (
    <>
      <path d="M14 3h7v7m0-7L10 14M10 4H4v16h16v-6" />
    </>
  ),
  chevron: <path d="m9 5 7 7-7 7" />,
  info: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 11v6m0-10v.1" />
    </>
  ),
  clock: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 2" />
    </>
  ),
  footsteps: (
    <>
      <ellipse cx="7" cy="7" rx="2.5" ry="4" transform="rotate(-20 7 7)" />
      <rect x="7" y="13" width="3" height="4" rx="1.5" transform="rotate(-20 8.5 15)" />
      <ellipse cx="17" cy="12" rx="2.5" ry="4" transform="rotate(20 17 12)" />
      <rect x="14" y="18" width="3" height="4" rx="1.5" transform="rotate(20 15.5 20)" />
    </>
  ),
  leaf: (
    <>
      <path d="M20 3C6 1 1 11 7 17S23 17 20 3ZM3 21 15 9" />
    </>
  ),
} as const

export function Icon({
  name,
  size = 20,
  className,
  style,
}: {
  name: keyof typeof paths
  size?: number
  className?: string
  style?: CSSProperties
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.65"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className={className}
      style={style}
    >
      {paths[name]}
    </svg>
  )
}
