import { useMutation } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { useEffect, useRef, useState } from 'react'

import { ClarificationForm } from '../components/clarification-form'
import { Icon } from '../components/icon'
import { JourneyAside } from '../components/journey-aside'
import { emptyInput, ProfileForm } from '../components/profile-form'
import { Results } from '../components/results'
import type { DemoScenario, RecommendationItem, ScoutInput, ScoutSession } from '../lib/contracts'
import { sessionClient } from '../lib/session-client'

export const Route = createFileRoute('/')({ component: Home })

type Operation =
  | { kind: 'start'; input: ScoutInput; scenario: DemoScenario }
  | {
      kind: 'answer'
      session: ScoutSession
      answers: Record<string, string>
      scenario: DemoScenario
    }
  | { kind: 'retry'; session: ScoutSession }

function Home() {
  const [view, setView] = useState<'discover' | 'saved'>('discover')
  const [input, setInput] = useState<ScoutInput>(emptyInput)
  const [session, setSession] = useState<ScoutSession | null>(null)
  const [answers, setAnswers] = useState<Record<string, string>>({})
  const [scenario, setScenario] = useState<DemoScenario>('normal')
  const [saved, setSaved] = useState<RecommendationItem[]>([])
  const [announcement, setAnnouncement] = useState('')
  const headingRef = useRef<HTMLHeadingElement>(null)
  const mutation = useMutation({
    mutationFn: (operation: Operation) => {
      if (operation.kind === 'start')
        return sessionClient.start(operation.input, operation.scenario)
      if (operation.kind === 'answer')
        return sessionClient.answer(operation.session, operation.answers, operation.scenario)
      return sessionClient.retry(operation.session)
    },
    onSuccess: (next) => {
      setSession(next)
      setInput((previous) => ({
        ...previous,
        target_directions: next.profile.target_directions,
        preferences: next.profile.preferences,
      }))
    },
  })
  const busy = mutation.isPending
  const completed = session?.current_stage === 'completed'
  const clarifying = session?.current_stage === 'clarify'
  const failed = session?.current_stage === 'failed'
  const step = busy || failed ? 2 : completed ? 3 : clarifying ? 1 : 0
  const savedView = view === 'saved'

  useEffect(() => {
    headingRef.current?.focus()
  }, [session, view])

  function edit() {
    setSession(null)
    setView('discover')
    mutation.reset()
  }

  function toggleSaved(item: RecommendationItem) {
    const exists = saved.some((entry) => entry.job.job_id === item.job.job_id)
    setSaved((previous) =>
      exists
        ? previous.filter((entry) => entry.job.job_id !== item.job.job_id)
        : [...previous, item],
    )
    setAnnouncement(`${exists ? '已取消收藏' : '已收藏'}：${item.job.title}`)
  }

  return (
    <div className="min-h-screen bg-base-200/25 text-base-content md:grid md:grid-cols-[216px_minmax(0,1fr)]">
      <a
        href="#main-content"
        className="sr-only z-50 rounded-lg bg-base-content p-3 text-base-100 focus:not-sr-only focus:fixed focus:top-3 focus:left-3"
      >
        跳转到主要内容
      </a>
      <aside className="flex border-b border-base-300 bg-base-100 px-4 py-4 md:sticky md:top-0 md:h-screen md:flex-col md:border-r md:border-b-0 md:px-5 md:py-8">
        <a
          href="/"
          className="flex shrink-0 items-center gap-2.5 self-start rounded-md md:px-1"
          aria-label="JobScout 首页"
        >
          <span className="flex size-9 items-center justify-center rounded-xl bg-primary/55 text-primary-content">
            <Icon name="compass" size={24} />
          </span>
          <span className="text-xl font-bold tracking-tight">
            JobScout<span className="text-primary-content">.</span>
          </span>
        </a>
        <div className="ml-auto md:mt-12 md:ml-0">
          <p className="mb-3 hidden px-3 text-[10px] font-semibold tracking-[0.15em] text-base-content/40 md:block">
            我的求职空间
          </p>
          <nav aria-label="主导航" className="flex gap-1 md:flex-col md:gap-2">
            <button
              disabled={busy}
              onClick={() => setView('discover')}
              aria-label="发现机会"
              aria-current={!savedView ? 'page' : undefined}
              className={`flex items-center gap-3 rounded-xl px-3 py-3 text-sm transition-colors disabled:opacity-50 ${!savedView ? 'bg-primary/20 font-semibold text-primary-content' : 'text-base-content/60 hover:bg-base-200/50'}`}
            >
              <Icon name="compass" size={19} />
              <span className="hidden sm:inline">发现机会</span>
            </button>
            <button
              disabled={busy}
              onClick={() => setView('saved')}
              aria-label={`收藏岗位，${saved.length} 个`}
              aria-current={savedView ? 'page' : undefined}
              className={`flex items-center gap-3 rounded-xl px-3 py-3 text-sm transition-colors disabled:opacity-50 ${savedView ? 'bg-secondary/45 font-semibold' : 'text-base-content/60 hover:bg-base-200/50'}`}
            >
              <Icon name="bookmark" size={19} />
              <span className="hidden sm:inline">收藏岗位</span>
              <span className="ml-auto rounded-md bg-base-200 px-1.5 py-0.5 text-[10px] tabular-nums">
                {saved.length}
              </span>
            </button>
          </nav>
        </div>
        <div className="mt-auto hidden md:block">
          <div className="rounded-xl border border-base-300 bg-base-200/25 p-4">
            <Icon name="leaf" size={22} className="text-primary-content" />
            <p className="mt-3 text-xs font-semibold">好工作，也要适合你。</p>
            <p className="mt-2 text-[11px] leading-5 text-base-content/55">
              少一点海投，
              <br />
              多一点有方向的探索。
            </p>
          </div>
          <div className="mt-6 flex items-center gap-2.5 border-t border-base-300 pt-5">
            <span className="flex size-8 items-center justify-center rounded-full bg-secondary/40 text-xs font-semibold">
              我
            </span>
            <div>
              <p className="text-xs font-medium">我的工作空间</p>
              <p className="mt-1 text-[10px] text-base-content/45">本地体验 · 无需登录</p>
            </div>
          </div>
        </div>
      </aside>
      <div className="min-w-0">
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
        <main
          id="main-content"
          className="mx-auto max-w-7xl px-5 pt-8 pb-10 sm:px-8 sm:pt-10 xl:px-12"
          aria-busy={busy}
        >
          <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
            <div>
              <p className="mb-3 text-[10px] font-bold tracking-[0.2em] text-primary-content">
                {savedView
                  ? 'KEEP THE POSSIBILITIES'
                  : completed
                    ? 'YOUR NEXT OPPORTUNITIES'
                    : 'YOUR NEXT CHAPTER'}
              </p>
              <h1
                ref={headingRef}
                tabIndex={-1}
                className="text-2xl font-semibold tracking-tight outline-none sm:text-[32px] sm:leading-snug"
              >
                {savedView
                  ? '心动的机会，慢慢比较。'
                  : completed
                    ? '下一站，从这些机会开始。'
                    : clarifying
                      ? '好机会，值得再聊一聊。'
                      : '好机会，从认识你开始。'}
              </h1>
              <p className="mt-3 text-sm leading-6 text-base-content/60">
                {savedView
                  ? '留住值得关注的岗位，为下一步做好准备。收藏仅在当前页面保留。'
                  : completed
                    ? '在不同方向中发现可能，也为每一次申请多做一点准备。'
                    : '聊聊你的经历和期待，让下一份工作更贴近你。'}
              </p>
            </div>
            {session && !busy && !savedView && (
              <button
                className="btn rounded-lg border border-base-300 bg-base-100 font-normal shadow-none btn-sm"
                onClick={edit}
              >
                <Icon name="compass" size={15} />
                调整求职条件
              </button>
            )}
          </div>
          {!savedView && (
            <ol
              aria-label="求职流程"
              className="mb-7 grid grid-cols-3 rounded-xl border border-base-300 bg-base-100 px-2 py-4 sm:px-5"
            >
              {['介绍自己', '确认方向', '发现机会'].map((label, index) => (
                <li
                  key={label}
                  aria-current={(step === 3 ? 2 : Math.min(step, 2)) === index ? 'step' : undefined}
                  className={`flex items-center justify-center gap-2 border-base-300 text-xs sm:justify-start sm:gap-3 sm:px-4 sm:text-sm ${index !== 2 ? 'border-r' : ''} ${step >= index ? 'font-medium text-base-content' : 'text-base-content/40'}`}
                >
                  <span
                    className={`flex size-6 shrink-0 items-center justify-center rounded-full text-[10px] sm:size-7 ${step > index ? 'bg-primary/25 text-primary-content' : step === index ? 'bg-base-content text-base-100' : 'bg-base-200'}`}
                  >
                    {step > index ? <Icon name="check" size={13} /> : `0${index + 1}`}
                  </span>
                  {label}
                </li>
              ))}
            </ol>
          )}
          {savedView ? (
            <Results
              key="saved"
              result={null}
              saved={saved}
              savedOnly
              onToggle={toggleSaved}
              onEdit={() => setView('discover')}
            />
          ) : (
            <div
              className={`grid items-start gap-6 ${completed ? '' : 'min-[1100px]:grid-cols-[minmax(0,1fr)_280px]'}`}
            >
              <div className="min-w-0">
                {busy ? (
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
                ) : (
                  <>
                    {mutation.isError && (
                      <div
                        role="alert"
                        className="mb-5 alert rounded-xl alert-soft text-sm alert-error"
                      >
                        <Icon name="info" />
                        <span>操作未完成，资料已保留，请重试。</span>
                        <button
                          className="btn btn-sm"
                          onClick={() => {
                            if (mutation.variables) mutation.mutate(mutation.variables)
                          }}
                        >
                          重试
                        </button>
                      </div>
                    )}
                    {!session && (
                      <ProfileForm
                        input={input}
                        onChange={setInput}
                        onSubmit={(next) => {
                          setAnswers({})
                          setInput(next)
                          mutation.mutate({ kind: 'start', input: next, scenario })
                        }}
                      />
                    )}
                    {session && clarifying && (
                      <ClarificationForm
                        key={`${session.session_id}-${session.clarification_questions.filter((question) => question.status === 'answered').length}`}
                        questions={session.clarification_questions}
                        answers={answers}
                        onChange={setAnswers}
                        onSubmit={(answers) =>
                          mutation.mutate({ kind: 'answer', session, answers, scenario })
                        }
                      />
                    )}
                    {session && failed && (
                      <section className="card border border-base-300 bg-base-100 p-6 sm:p-8">
                        <span className="mb-5 flex size-12 items-center justify-center rounded-full bg-accent/50 text-accent-content">
                          <Icon name="info" size={24} />
                        </span>
                        <h2 className="text-xl font-semibold">这次搜索遇到了一点问题</h2>
                        {session.errors.map((error) => (
                          <div key={`${error.code}-${error.stage}`} role="alert">
                            <p className="mt-3 text-sm leading-7 text-base-content/65">
                              {error.message}
                            </p>
                            <p className="mt-2 text-xs text-base-content/45">
                              {error.code} · {error.stage}
                            </p>
                          </div>
                        ))}
                        <p className="mt-4 text-xs text-base-content/55">
                          当前为失败场景演示，重试后可查看恢复结果。
                        </p>
                        <div className="mt-7">
                          <button
                            className="btn rounded-xl border-0 btn-primary"
                            onClick={() => mutation.mutate({ kind: 'retry', session })}
                          >
                            重新尝试
                            <Icon name="arrow" size={17} />
                          </button>
                        </div>
                      </section>
                    )}
                    {completed && (
                      <Results
                        key={session.session_id}
                        result={session.recommendation}
                        saved={saved}
                        onToggle={toggleSaved}
                        onEdit={edit}
                      />
                    )}
                  </>
                )}
              </div>
              {!completed && <JourneyAside />}
            </div>
          )}
          <footer className="mt-9 flex flex-wrap items-center justify-between gap-2 border-t border-base-300 pt-5 text-[10px] text-base-content/45">
            <span>JobScout · 为你的下一步，找一点方向。</span>
            <span>示例体验 · 所有岗位均为虚构数据</span>
          </footer>
        </main>
      </div>
      <div className="sr-only" aria-live="polite">
        {announcement}
      </div>
    </div>
  )
}
