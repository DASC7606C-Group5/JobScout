import { useMatchRoute } from '@tanstack/react-router'

import type { DemoScenario } from '../../lib/contracts'
import { useScout } from '../../state/scout-context'
import { Icon } from '../icon'

export function WorkspaceHeader() {
  const scenario = useScout((state) => state.scenario)
  const setScenario = useScout((state) => state.setScenario)
  const busy = useScout((state) => state.busy)
  const session = useScout((state) => state.session)
  const matchRoute = useMatchRoute()
  const savedView = Boolean(matchRoute({ to: '/saved' }))
  return (
    <header className="flex min-h-20 flex-wrap items-center justify-between gap-3 border-b border-base-300 px-5 py-4 sm:px-8 xl:px-12">
      <p className="flex items-center gap-2 text-xs text-base-content/55">
        工作空间
        <Icon name="chevron" size={12} />
        <span className="text-base-content/85">{savedView ? '收藏岗位' : '发现机会'}</span>
      </p>
      <label className="flex items-center gap-2.5 text-xs">
        <span className="flex items-center gap-1.5 text-base-content/60">
          <span className="size-1.5 rounded-full bg-primary-content/60" />
          示例模式
        </span>
        <select
          className="select w-28 rounded-lg border border-base-300 bg-base-100 text-xs select-sm"
          aria-label="演示场景"
          value={scenario}
          disabled={busy || Boolean(session)}
          onChange={(event) => setScenario(event.target.value as DemoScenario)}
        >
          <option value="normal">正常流程</option>
          <option value="clarify">补充追问</option>
          <option value="empty">空结果</option>
          <option value="error">检索失败</option>
        </select>
      </label>
    </header>
  )
}
