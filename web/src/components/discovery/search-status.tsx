import type { WorkflowError } from '../../lib/contracts'
import { Icon } from '../icon'
export function SearchLoading() {
  return (
    <section
      className="card min-h-96 items-center justify-center border border-base-300 bg-base-100 p-8 text-center"
      aria-live="polite"
    >
      <span className="mb-6 flex size-20 items-center justify-center rounded-full bg-primary/20 text-primary-content">
        <span className="loading loading-lg loading-spinner" />
      </span>
      <h2 className="text-xl font-semibold">正在为你探索机会</h2>
      <p className="mt-3 max-w-sm text-sm leading-7 text-base-content/60">
        整理你的求职条件，准备岗位和申请建议。
        <br />
        这段旅程，马上继续。
      </p>
      <p className="mt-6 text-xs text-base-content/40">当前为示例流程</p>
    </section>
  )
}
export function SearchFailure({
  errors,
  onRetry,
}: {
  errors: WorkflowError[]
  onRetry: () => void
}) {
  return (
    <section className="card border border-base-300 bg-base-100 p-6 sm:p-8">
      <span className="mb-5 flex size-12 items-center justify-center rounded-full bg-accent/50 text-accent-content">
        <Icon name="info" size={24} />
      </span>
      <h2 className="text-xl font-semibold">这次搜索遇到了一点问题</h2>
      {errors.map((error) => (
        <div key={`${error.code}-${error.stage}`} role="alert">
          <p className="mt-3 text-sm leading-7 text-base-content/65">{error.message}</p>
          <p className="mt-2 text-xs text-base-content/45">
            {error.code} · {error.stage}
          </p>
        </div>
      ))}
      <p className="mt-4 text-xs text-base-content/55">
        当前为失败场景演示，重试后可查看恢复结果。
      </p>
      <div className="mt-7">
        <button className="btn rounded-xl border-0 btn-primary" onClick={onRetry}>
          重新尝试
          <Icon name="arrow" size={17} />
        </button>
      </div>
    </section>
  )
}
