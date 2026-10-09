import { AsyncButton } from '../async-button'
import { Icon } from '../icon'

export function ResultEmpty({
  savedOnly,
  onEdit,
  hiddenCount = 0,
}: {
  savedOnly: boolean
  onEdit: () => unknown
  hiddenCount?: number
}) {
  return (
    <section className="card items-center border border-base-300 bg-base-100 px-6 py-16 text-center">
      <span className="mb-5 flex size-16 items-center justify-center rounded-full bg-secondary/35">
        <Icon name={savedOnly ? 'bookmark' : 'search'} size={28} />
      </span>
      <h2 className="text-xl font-semibold">
        {savedOnly
          ? 'No saved jobs yet'
          : hiddenCount
            ? 'All jobs are hidden'
            : 'No matching jobs found yet'}
      </h2>
      <p className="mt-3 max-w-sm text-sm leading-7 text-base-content/60">
        {savedOnly
          ? 'Save jobs that interest you to compare them here.'
          : hiddenCount
            ? `${hiddenCount} ${hiddenCount === 1 ? 'job is' : 'jobs are'} still available in this search. Choose Hidden above to review or show them again.`
            : 'Try another type of job or broaden your location preferences.'}
      </p>
      {!hiddenCount && (
        <AsyncButton type="button" className="btn mt-7 border-0 btn-primary" onClick={onEdit}>
          {savedOnly ? 'Explore jobs' : 'Edit search criteria'}
          <Icon name="arrow" size={17} />
        </AsyncButton>
      )}
    </section>
  )
}
