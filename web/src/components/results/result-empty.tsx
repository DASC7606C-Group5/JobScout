import { Icon } from '../icon'

export function ResultEmpty({ savedOnly, onEdit }: { savedOnly: boolean; onEdit: () => void }) {
  return (
    <section className="card items-center border border-base-300 bg-base-100 px-6 py-16 text-center">
      <span className="mb-5 flex size-16 items-center justify-center rounded-full bg-secondary/35">
        <Icon name={savedOnly ? 'bookmark' : 'search'} size={28} />
      </span>
      <h2 className="text-xl font-semibold">
        {savedOnly ? 'Save jobs that catch your eye' : 'No matching jobs found yet'}
      </h2>
      <p className="mt-3 max-w-sm text-sm leading-7 text-base-content/60">
        {savedOnly
          ? 'Save roles that interest you to compare them during this visit.'
          : 'Try another job direction or broaden your location preferences.'}
      </p>
      <button className="btn mt-7 border-0 btn-primary" onClick={onEdit}>
        {savedOnly ? 'Explore opportunities' : 'Edit search criteria'}
        <Icon name="arrow" size={17} />
      </button>
    </section>
  )
}
