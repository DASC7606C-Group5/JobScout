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
        {savedOnly ? '把心动的机会留在这里' : '暂时没有找到合适的岗位'}
      </h2>
      <p className="mt-3 max-w-sm text-sm leading-7 text-base-content/60">
        {savedOnly
          ? '留住感兴趣的机会，慢慢比较。'
          : '试着放宽地点限制，或增加一个求职方向，再探索一次。'}
      </p>
      <button className="btn mt-7 rounded-xl border-0 btn-primary" onClick={onEdit}>
        {savedOnly ? '去发现机会' : '调整求职条件'}
        <Icon name="arrow" size={17} />
      </button>
    </section>
  )
}
