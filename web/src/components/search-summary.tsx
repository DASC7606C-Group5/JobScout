import { useState } from 'react'

import type { SearchSummary as Summary } from '../lib/contracts'
import { summaryDraft, summaryFields, summaryUpdates } from '../lib/search-summary'
import { useScoutSession } from '../state/session-context'

export function SearchSummary({ summary }: { summary: Summary }) {
  const { answer, busy, session } = useScoutSession()
  const original = summaryDraft(summary.profile)
  const [draft, setDraft] = useState(original)
  const [message, setMessage] = useState('')
  const updates = summaryUpdates(original, draft, summary.editable_fields)
  const changed = Object.keys(updates).length > 0 || Boolean(message.trim())
  const editableFields = new Set(summary.editable_fields)
  const current = summary.revision === session?.revision
  return (
    <form
      className="card border border-base-300 bg-base-100 p-5 sm:p-7"
      onSubmit={(event) => {
        event.preventDefault()
        if (changed)
          answer({ action: 'edit_conditions', profile_updates: updates, message: message.trim() })
      }}
    >
      <h2 className="text-lg font-semibold">确认你的画像与搜索条件</h2>
      <p className="mt-3 text-sm leading-6 text-base-content/65">
        {summary.coverage_notice} 薪资、行业和工作方式为参考偏好，来源未核实的信息会注明。
      </p>
      <p className="mt-2 text-xs text-base-content/60">
        每行一项，也可使用逗号分隔。保存修改后，请再次确认；确认前不会检索岗位。
      </p>
      <fieldset disabled={busy} className="mt-6 min-w-0 space-y-5">
        <div className="grid gap-4 sm:grid-cols-2">
          {summaryFields.map(([key, label, kind]) => {
            const editable = editableFields.has(key)
            const id = `summary-${key}`
            if (kind === 'boolean')
              return (
                <label key={key} className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    className="checkbox checkbox-sm"
                    checked={draft[key] === true}
                    disabled={!editable}
                    onChange={(event) => setDraft({ ...draft, [key]: event.target.checked })}
                  />
                  {label}
                </label>
              )
            const unrestricted =
              (key === 'preferences.location' &&
                draft['preferences.location_unrestricted'] === true) ||
              (key === 'preferences.employment_type' &&
                draft['preferences.employment_type_unrestricted'] === true)
            return (
              <div key={key}>
                <label htmlFor={id} className="mb-2 block text-sm">
                  {label}
                </label>
                <textarea
                  id={id}
                  className="textarea w-full"
                  rows={kind === 'array' ? 3 : 1}
                  value={String(draft[key])}
                  readOnly={!editable}
                  disabled={unrestricted}
                  maxLength={10000}
                  onChange={(event) => setDraft({ ...draft, [key]: event.target.value })}
                />
              </div>
            )
          })}
        </div>
        {summary.missing_fields.length > 0 && (
          <output className="block rounded-xl bg-accent/25 p-3 text-sm">
            还需确认：
            {summary.missing_fields
              .map((key) => summaryFields.find(([field]) => field === key)?.[1] ?? key)
              .join('、')}
          </output>
        )}
        <div>
          <label htmlFor="summary-message" className="mb-2 block text-sm">
            补充或纠正搜索条件
          </label>
          <textarea
            id="summary-message"
            className="textarea w-full"
            value={message}
            onChange={(event) => setMessage(event.target.value)}
            maxLength={10000}
          />
        </div>
        <div className="flex flex-wrap gap-3 border-t border-base-300 pt-5">
          <button type="submit" disabled={!changed} className="btn rounded-xl">
            保存修改
          </button>
          <button
            type="button"
            disabled={changed || !summary.ready || summary.confirmed || !current}
            className="btn rounded-xl btn-primary"
            onClick={() => answer({ action: 'confirm_search' })}
          >
            确认并开始搜索
          </button>
        </div>
        {!current && (
          <p className="text-xs text-base-content/65">摘要版本已过期，请刷新会话后再确认搜索。</p>
        )}
        {changed && (
          <p className="text-xs text-base-content/65">
            有未保存的修改。请保存并检查最新摘要后再确认搜索。
          </p>
        )}
      </fieldset>
    </form>
  )
}
