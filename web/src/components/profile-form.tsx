import { useEffect, useRef, useState } from 'react'

import type { ScoutInput } from '../lib/contracts'
import { readResume } from '../lib/session-client'
import { Icon } from './icon'

export const emptyInput: ScoutInput = {
  description: '',
  resume: null,
  target_directions: [],
  preferences: {
    location: '',
    location_unrestricted: false,
    employment_type: null,
    salary_range: null,
    work_mode: null,
    industry: null,
  },
}

export function ProfileForm({
  input,
  onChange,
  onSubmit,
}: {
  input: ScoutInput
  onChange: (input: ScoutInput) => void
  onSubmit: (input: ScoutInput) => void
}) {
  const [directions, setDirections] = useState(input.target_directions.join('，'))
  const [error, setError] = useState('')
  const [reading, setReading] = useState(false)
  const [dragging, setDragging] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)
  const descriptionRef = useRef<HTMLTextAreaElement>(null)
  const readId = useRef(0)
  const preferences = input.preferences

  useEffect(
    () => () => {
      readId.current += 1
    },
    [],
  )

  function updateDirections(value: string) {
    setDirections(value)
    onChange({
      ...input,
      target_directions: value
        .split(/[,，、]/)
        .map((part) => part.trim())
        .filter(Boolean),
    })
  }

  function updatePreference<K extends keyof ScoutInput['preferences']>(
    key: K,
    value: ScoutInput['preferences'][K],
  ) {
    onChange({ ...input, preferences: { ...preferences, [key]: value } })
  }

  async function attach(file: File | undefined) {
    if (!file) return
    const id = ++readId.current
    setReading(true)
    setError('')
    try {
      const resume = await readResume(file)
      if (id === readId.current) onChange({ ...input, resume })
    } catch (cause) {
      if (id === readId.current)
        setError(cause instanceof Error ? cause.message : '文件读取失败，请重试。')
    } finally {
      if (id === readId.current) setReading(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  function fillExample() {
    setError('')
    setDirections('前端开发，数据分析')
    onChange({
      description:
        '我是计算机专业应届毕业生，熟悉 React、TypeScript 和 Python，做过校园活动网站与数据分析项目。希望找到能参与真实产品、与团队一起成长的初级岗位。',
      resume: null,
      target_directions: ['前端开发', '数据分析'],
      preferences: {
        location: '香港',
        location_unrestricted: false,
        employment_type: 'full-time',
        salary_range: 'HK$ 20,000–28,000 / 月',
        work_mode: null,
        industry: null,
      },
    })
  }

  return (
    <form
      className="card border border-base-300 bg-base-100 shadow-sm"
      onSubmit={(event) => {
        event.preventDefault()
        if (reading) return
        if (!input.description.trim() && !input.resume) {
          setError('请填写个人介绍，或添加一份 TXT 简历。')
          descriptionRef.current?.focus()
          return
        }
        setError('')
        onSubmit({
          ...input,
          description: input.description.trim(),
          target_directions: [
            ...new Set(
              directions
                .split(/[,，、]/)
                .map((part) => part.trim())
                .filter(Boolean),
            ),
          ],
          preferences: {
            ...preferences,
            location: preferences.location_unrestricted
              ? null
              : preferences.location?.trim() || null,
          },
        })
      }}
    >
      <div className="border-b border-base-300 px-5 py-5 sm:px-7">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <span className="flex size-10 items-center justify-center rounded-xl bg-secondary/45">
              <Icon name="file" />
            </span>
            <div>
              <h2 className="text-lg font-semibold">先认识一下你</h2>
              <p className="mt-1 text-xs text-base-content/60">你的经历，是发现好机会的起点</p>
            </div>
          </div>
          <button
            type="button"
            className="btn btn-ghost font-normal text-base-content/70 btn-sm"
            onClick={fillExample}
            disabled={reading}
          >
            <Icon name="sparkles" size={15} />
            填入示例
          </button>
        </div>
      </div>
      <fieldset disabled={reading} className="min-w-0 space-y-6 p-5 sm:p-7">
        <div>
          <div className="mb-2.5 flex items-center justify-between">
            <label htmlFor="description" className="text-sm font-semibold">
              个人介绍
            </label>
            <span className="text-xs text-base-content/55">与简历至少填写一项</span>
          </div>
          <textarea
            ref={descriptionRef}
            id="description"
            className="textarea min-h-36 w-full resize-y rounded-xl border border-base-300 bg-base-200/25 p-4 text-sm leading-7"
            placeholder="聊聊你的教育背景、擅长的技能、项目或实习经历，以及你对下一份工作的期待……"
            maxLength={10000}
            value={input.description}
            onChange={(event) => onChange({ ...input, description: event.target.value })}
            aria-describedby="description-hint"
          />
          <div
            id="description-hint"
            className="mt-2 flex justify-between gap-3 text-xs text-base-content/55"
          >
            <span>不必写得完美，稍后还可以补充。</span>
            <span className="shrink-0 tabular-nums">
              {input.description.length.toLocaleString()} / 10,000
            </span>
          </div>
        </div>
        <div>
          <label
            className={`relative flex cursor-pointer items-center gap-4 rounded-xl border border-dashed p-4 transition-colors ${dragging ? 'border-primary-content bg-primary/15' : 'border-base-content/20 bg-base-200/20 hover:bg-base-200/45'}`}
          >
            <input
              ref={fileRef}
              type="file"
              accept=".txt,text/plain"
              className="absolute inset-0 h-full w-full cursor-pointer opacity-0"
              aria-label="添加 TXT 简历"
              disabled={reading}
              onDragOver={(event) => {
                event.preventDefault()
                setDragging(true)
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={(event) => {
                event.preventDefault()
                setDragging(false)
                if (!reading) void attach(event.dataTransfer.files[0])
              }}
              onChange={(event) => {
                void attach(event.target.files?.[0])
              }}
            />
            <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-base-100">
              <Icon name={input.resume ? 'file' : 'upload'} />
            </span>
            <span className="min-w-0">
              <span className="block truncate text-sm font-medium">
                {reading ? '正在读取简历…' : input.resume?.name || '添加简历，或者拖到这里'}
              </span>
              <span className="mt-1 block text-xs text-base-content/55">
                TXT · UTF-8 · 最大 1 MB · 可选
              </span>
            </span>
            {input.resume && (
              <Icon name="check" className="ml-auto shrink-0 text-primary-content" />
            )}
          </label>
          {input.resume && (
            <button
              type="button"
              className="btn mt-2 btn-ghost btn-xs"
              onClick={() => {
                onChange({ ...input, resume: null })
                setError('')
              }}
            >
              移除简历
            </button>
          )}
        </div>
        <div className="border-t border-base-300 pt-6">
          <div className="mb-5 flex items-center gap-2">
            <Icon name="compass" size={19} />
            <h3 className="text-sm font-semibold">你想往哪个方向走？</h3>
          </div>
          <label htmlFor="directions" className="mb-2 block text-sm">
            求职方向 <span className="ml-1 text-xs text-base-content/50">可填写多个</span>
          </label>
          <input
            id="directions"
            className="input w-full rounded-xl border border-base-300 bg-base-200/25 text-sm"
            placeholder="例如：前端开发，数据分析"
            maxLength={300}
            value={directions}
            onChange={(event) => updateDirections(event.target.value)}
          />
          <div className="mt-2.5 flex flex-wrap gap-2">
            {['前端开发', '数据分析', '产品设计', '软件工程'].map((direction) => {
              const selected = directions
                .split(/[,，、]/)
                .map((part) => part.trim())
                .includes(direction)
              return (
                <button
                  type="button"
                  key={direction}
                  aria-pressed={selected}
                  className={`btn border font-normal shadow-none btn-xs ${selected ? 'border-primary-content/20 bg-primary/20 text-primary-content' : 'border-base-300 bg-base-100 text-base-content/65'}`}
                  onClick={() => {
                    const list = directions
                      .split(/[,，、]/)
                      .map((part) => part.trim())
                      .filter(Boolean)
                    updateDirections(
                      (selected
                        ? list.filter((part) => part !== direction)
                        : [...list, direction]
                      ).join('，'),
                    )
                  }}
                >
                  {selected ? '✓' : '+'} {direction}
                </button>
              )
            })}
          </div>
        </div>
        <div className="grid gap-5 sm:grid-cols-2">
          <div>
            <label htmlFor="location" className="mb-2 block text-sm">
              工作地点
            </label>
            <input
              id="location"
              className="input w-full rounded-xl border border-base-300 bg-base-200/25 text-sm"
              placeholder="例如：香港、深圳"
              maxLength={100}
              disabled={preferences.location_unrestricted}
              value={preferences.location ?? ''}
              onChange={(event) => updatePreference('location', event.target.value)}
            />
            <label className="mt-2.5 flex w-fit cursor-pointer items-center gap-2 text-xs text-base-content/65">
              <input
                type="checkbox"
                className="checkbox checkbox-xs"
                checked={preferences.location_unrestricted}
                onChange={(event) =>
                  updatePreference('location_unrestricted', event.target.checked)
                }
              />
              我接受不限地点
            </label>
          </div>
          <div>
            <label htmlFor="employment" className="mb-2 block text-sm">
              工作类型
            </label>
            <select
              id="employment"
              className="select w-full rounded-xl border border-base-300 bg-base-100 text-sm"
              value={preferences.employment_type ?? ''}
              onChange={(event) => updatePreference('employment_type', event.target.value || null)}
            >
              <option value="">还没想好，稍后确认</option>
              <option value="full-time">全职</option>
              <option value="internship">实习</option>
              <option value="part-time">兼职</option>
              {preferences.employment_type &&
                !['full-time', 'internship', 'part-time'].includes(preferences.employment_type) && (
                  <option value={preferences.employment_type}>{preferences.employment_type}</option>
                )}
            </select>
          </div>
          <div>
            <label htmlFor="salary" className="mb-2 block text-sm">
              期望薪资 <span className="text-xs text-base-content/50">选填</span>
            </label>
            <input
              id="salary"
              className="input w-full rounded-xl border border-base-300 bg-base-200/25 text-sm"
              placeholder="例如：HK$ 20,000–28,000 / 月"
              maxLength={100}
              value={preferences.salary_range ?? ''}
              onChange={(event) => updatePreference('salary_range', event.target.value || null)}
            />
          </div>
          <div>
            <label htmlFor="work-mode" className="mb-2 block text-sm">
              工作方式 <span className="text-xs text-base-content/50">选填</span>
            </label>
            <select
              id="work-mode"
              className="select w-full rounded-xl border border-base-300 bg-base-100 text-sm"
              value={preferences.work_mode ?? ''}
              onChange={(event) => updatePreference('work_mode', event.target.value || null)}
            >
              <option value="">不限</option>
              <option value="onsite">办公室</option>
              <option value="hybrid">混合办公</option>
              <option value="remote">远程</option>
              {preferences.work_mode &&
                !['onsite', 'hybrid', 'remote'].includes(preferences.work_mode) && (
                  <option value={preferences.work_mode}>{preferences.work_mode}</option>
                )}
            </select>
          </div>
        </div>
        {error && (
          <div className="alert rounded-xl alert-soft text-sm alert-error" role="alert">
            <Icon name="info" size={18} />
            {error}
          </div>
        )}
        <div className="flex flex-wrap items-center justify-between gap-4 border-t border-base-300 pt-5">
          <p className="max-w-64 text-xs leading-5 text-base-content/55">
            资料仅在当前页面中使用。
            <br />
            示例模式不会上传你的简历或个人信息。
          </p>
          <button
            type="submit"
            className="btn min-w-40 rounded-xl border-0 btn-primary"
            disabled={reading}
          >
            {reading ? '正在读取…' : '发现适合我的机会'}
            <Icon name="arrow" size={18} />
          </button>
        </div>
      </fieldset>
    </form>
  )
}
