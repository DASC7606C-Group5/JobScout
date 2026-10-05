import type { WorkflowError } from '../../lib/contracts'
import { Icon } from '../icon'
const stages: Record<string, string> = {
  ingest: '正在读取你的资料',
  extract: '正在理解你的经历',
  validate: '正在核对画像与条件',
  clarify: '正在整理需要确认的信息',
  confirm: '正在更新搜索摘要',
  plan: '正在准备搜索计划',
  search: '正在检索支持的招聘来源',
  retrieve: '正在检索支持的招聘来源',
  normalize: '正在整理岗位',
  understand: '正在核对岗位要求',
  assess_coverage: '正在检查岗位覆盖',
  recommend: '正在分析匹配证据',
  present: '正在整理推荐结果',
}
export function SearchLoading({ stage }: { stage: string }) {
  return (
    <section
      className="card min-h-96 items-center justify-center border border-base-300 bg-base-100 p-8 text-center"
      aria-live="polite"
    >
      <span className="mb-6 flex size-20 items-center justify-center rounded-full bg-primary/20 text-primary-content">
        <span className="loading loading-lg loading-spinner" />
      </span>
      <h2 className="text-xl font-semibold">{stages[stage] ?? '正在处理当前步骤'}</h2>
      <p className="mt-3 max-w-sm text-sm leading-7 text-base-content/60">
        整理你的求职条件，准备岗位和申请建议。
        <br />
        这段旅程，马上继续。
      </p>
      <p className="mt-6 text-xs text-base-content/40">搜索可能需要一些时间，请稍候。</p>
    </section>
  )
}
export function SearchFailure({
  errors,
  onRetry,
  retryable,
}: {
  errors: WorkflowError[]
  onRetry: () => void
  retryable: boolean
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
      <div className="mt-7">
        <button
          className="btn rounded-xl border-0 btn-primary"
          disabled={!retryable}
          onClick={onRetry}
        >
          重新尝试
          <Icon name="arrow" size={17} />
        </button>
      </div>
    </section>
  )
}
