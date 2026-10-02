import { Icon } from '../icon'
export function ResultWarnings({ warnings }: { warnings: string[] }) {
  return warnings.map((warning) => (
    <output
      key={warning}
      className="mb-5 flex items-start gap-2.5 rounded-xl border border-accent/70 bg-accent/20 px-4 py-3 text-left text-xs leading-6 text-base-content/70"
    >
      <Icon name="info" size={17} className="mt-1 shrink-0" />
      {warning}
    </output>
  ))
}
