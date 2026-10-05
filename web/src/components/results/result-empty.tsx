import { Icon } from '../icon'
import { ResultWarnings } from './result-warnings'
export function ResultEmpty({
  savedOnly,
  onEdit,
  warnings,
}: {
  savedOnly: boolean
  onEdit: () => void
  warnings: string[]
}) {
  return (
    <section className="card items-center border border-base-300 bg-base-100 px-6 py-16 text-center">
      <ResultWarnings warnings={warnings} />
      <span className="mb-5 flex size-16 items-center justify-center rounded-full bg-secondary/35">
        <Icon name={savedOnly ? 'bookmark' : 'search'} size={28} />
      </span>
      <h2 className="text-xl font-semibold">
        {savedOnly ? 'Save jobs that catch your eye' : 'No matching jobs found yet'}
      </h2>
      <p className="mt-3 max-w-sm text-sm leading-7 text-base-content/60">
        {savedOnly
          ? 'Keep track of roles you’re interested in and compare them later.'
          : 'Try broadening your location preferences or adding another job direction.'}
      </p>
      <button className="btn mt-7 rounded-xl border-0 btn-primary" onClick={onEdit}>
        {savedOnly ? 'Explore opportunities' : 'Edit search criteria'}
        <Icon name="arrow" size={17} />
      </button>
    </section>
  )
}
