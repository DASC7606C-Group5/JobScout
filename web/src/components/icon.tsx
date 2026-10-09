import {
  Server,
  SlidersHorizontal,
  ArrowUpDown,
  Compass,
  Search,
  Bookmark,
  Plus,
  PanelLeftClose,
  Trash2,
  ArrowRight,
  ArrowUp,
  Upload,
  FileText,
  MapPin,
  BriefcaseBusiness,
  Sparkles,
  Check,
  X,
  ExternalLink,
  ChevronRight,
  CodeXml,
  Info,
  Clock,
  Footprints,
  Leaf,
  MessageCircle,
  EyeOff,
  Heart,
} from 'lucide-react'
import type { CSSProperties } from 'react'

const icons = {
  github: CodeXml,
  server: Server,
  settings: SlidersHorizontal,
  sort: ArrowUpDown,
  compass: Compass,
  search: Search,
  bookmark: Bookmark,
  plus: Plus,
  panel: PanelLeftClose,
  trash: Trash2,
  arrow: ArrowRight,
  send: ArrowUp,
  upload: Upload,
  file: FileText,
  pin: MapPin,
  briefcase: BriefcaseBusiness,
  sparkles: Sparkles,
  check: Check,
  close: X,
  external: ExternalLink,
  chevron: ChevronRight,
  info: Info,
  clock: Clock,
  footsteps: Footprints,
  leaf: Leaf,
  message: MessageCircle,
  hidden: EyeOff,
  heart: Heart,
} as const

export function Icon({
  name,
  size = 20,
  className,
  style,
}: {
  name: keyof typeof icons
  size?: number
  className?: string
  style?: CSSProperties
}) {
  const Component = icons[name]
  return (
    <Component
      size={size}
      strokeWidth={1.65}
      aria-hidden="true"
      className={className}
      style={style}
    />
  )
}
