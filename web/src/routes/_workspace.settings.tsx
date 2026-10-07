import { useQuery, useQueryClient } from '@tanstack/react-query'
import { createFileRoute, useRouter } from '@tanstack/react-router'
import { useState, useSyncExternalStore } from 'react'
import { useForm, useWatch } from 'react-hook-form'

import { Icon } from '../components/icon'
import { PageHeading } from '../components/layout/page-heading'
import { accountRequest, changeAccount, currentAccount, subscribeAccount } from '../lib/auth-client'

export const Route = createFileRoute('/_workspace/settings')({ component: SettingsPage })
type Role = 'semantic' | 'decision'
interface ModelInfo {
  personal: boolean
  endpoint_id: string | null
  model: string
  key_configured: boolean
  server_provider: string
  server_model: string
  server_key_configured: boolean
  thinking: boolean
  server_thinking: boolean
}
interface ModelSettings {
  roles: Record<Role, ModelInfo>
  endpoints: { id: string; name: string; thinking_supported: boolean }[]
  personal_available: boolean
}
interface Usage {
  remaining: number
  limit: number
  server_remaining: number
  day: string
  timezone: string
}
interface ModelFields {
  endpoint_id: string
  model: string
  api_key: string
  thinking: boolean
}
const settingsKey = ['model-settings'] as const

interface ModelFormProps {
  role: Role
  info: ModelInfo
  settings: ModelSettings
}

function useModelForm({ role, info, settings }: ModelFormProps) {
  const cache = useQueryClient()
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [testing, setTesting] = useState(false)
  const {
    register,
    handleSubmit,
    control,
    reset,
    formState: { isSubmitting },
  } = useForm<ModelFields>({
    defaultValues: {
      endpoint_id: info.endpoint_id ?? 'server',
      model: info.personal ? info.model : '',
      api_key: '',
      thinking: info.personal && info.thinking,
    },
  })
  const endpoint = useWatch({ control, name: 'endpoint_id' })
  const thinkingSupported =
    settings.endpoints.find((item) => item.id === endpoint)?.thinking_supported ?? false
  const save = handleSubmit(async (values) => {
    setMessage('')
    setError('')
    try {
      if (values.endpoint_id === 'server')
        await accountRequest(`/settings/models/${role}`, 'DELETE')
      else
        await accountRequest(`/settings/models/${role}`, 'PUT', {
          endpoint_id: values.endpoint_id,
          model: values.model.trim(),
          thinking: thinkingSupported && values.thinking,
          ...(values.api_key ? { api_key: values.api_key } : {}),
        })
      reset({ ...values, api_key: '' })
      setMessage('Configuration saved')
      await cache.invalidateQueries({ queryKey: settingsKey })
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'Could not save settings.')
    }
  })
  const test = async () => {
    setTesting(true)
    setError('')
    setMessage('')
    try {
      await accountRequest(`/settings/models/${role}/test`, 'POST')
      setMessage('Connection verified')
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'Connection test failed.')
    }
    setTesting(false)
    await cache.invalidateQueries({ queryKey: ['model-usage'] })
  }
  return {
    register,
    isSubmitting,
    testing,
    endpoint,
    thinkingSupported,
    save,
    test,
    message,
    error,
  }
}

function ModelForm({ role, info, settings }: ModelFormProps) {
  const {
    register,
    isSubmitting,
    testing,
    endpoint,
    thinkingSupported,
    save,
    test,
    message,
    error,
  } = useModelForm({ role, info, settings })
  return (
    <form
      onSubmit={(event) => void save(event)}
      className="card border border-base-300 bg-base-100"
    >
      <div className="card-body gap-5 p-5 sm:p-6">
        <fieldset disabled={isSubmitting || testing} className="fieldset min-w-0 gap-5 p-0 text-sm">
          <legend className="fieldset-legend w-full justify-start gap-2 pt-0 pb-5 text-base whitespace-normal">
            <Icon
              name={role === 'semantic' ? 'file' : 'compass'}
              className="shrink-0 text-base-content/70"
            />
            {role === 'semantic' ? 'Profile and job analysis' : 'Search decisions and matching'}
          </legend>
          <label className="flex flex-col gap-2">
            Model service
            <select className="select w-full" {...register('endpoint_id')}>
              <option value="server">Use server configuration ({info.server_provider})</option>
              {settings.endpoints.map((item) => (
                <option key={item.id} value={item.id} disabled={!settings.personal_available}>
                  {item.name}
                </option>
              ))}
            </select>
          </label>
          {endpoint === 'server' ? (
            <dl className="grid min-w-0 grid-cols-[6rem_minmax(0,1fr)] gap-x-4 gap-y-2 text-sm sm:grid-cols-[7rem_minmax(0,1fr)]">
              <dt className="text-base-content/70">Server model</dt>
              <dd className="break-all">{info.server_model}</dd>
              <dt className="text-base-content/70">Thinking</dt>
              <dd>{info.server_thinking ? 'Requested' : 'Not requested'}</dd>
            </dl>
          ) : (
            <>
              <label className="flex flex-col gap-2">
                Model name
                <input className="input w-full" maxLength={128} required {...register('model')} />
              </label>
              <label className="flex flex-col gap-2">
                API key
                <input
                  className="input w-full"
                  type="password"
                  autoComplete="off"
                  maxLength={4096}
                  required={!info.personal || endpoint !== info.endpoint_id}
                  {...register('api_key')}
                />
              </label>
              {thinkingSupported && (
                <div>
                  <label className="flex items-center gap-3">
                    <input
                      type="checkbox"
                      className="checkbox checkbox-sm"
                      {...register('thinking')}
                    />
                    Request thinking
                  </label>
                  <p className="mt-2 text-base-content/70">
                    Requires a model that supports reasoning. This can increase response time and
                    token use.
                  </p>
                </div>
              )}
              {info.personal && endpoint === info.endpoint_id && (
                <p className="text-base-content/70">
                  A key is saved. Leave this field empty to keep it.
                </p>
              )}
            </>
          )}
          <div className="flex flex-wrap items-center gap-3 border-t border-base-300 pt-5">
            <button className="btn btn-sm" type="submit">
              {isSubmitting ? 'Saving…' : 'Save configuration'}
            </button>
            <button
              className="btn btn-ghost btn-sm"
              type="button"
              disabled={!info.key_configured}
              onClick={() => void test()}
            >
              {testing ? 'Testing…' : 'Test'}
            </button>
            {message && (
              <output className="flex items-center gap-1.5 text-xs text-base-content/70">
                <Icon name="check" size={16} className="shrink-0" />
                {message}
              </output>
            )}
          </div>
        </fieldset>
        {error && (
          <div role="alert" className="alert alert-soft alert-error">
            {error}
          </div>
        )}
      </div>
    </form>
  )
}

function PasswordForm() {
  const router = useRouter()
  const [error, setError] = useState('')
  const {
    register,
    handleSubmit,
    reset,
    formState: { isSubmitting },
  } = useForm<{ current_password: string; new_password: string }>()
  const submit = handleSubmit(async (values) => {
    setError('')
    try {
      await accountRequest('/auth/password', 'POST', values)
      reset()
      changeAccount(null)
      await router.navigate({ to: '/login' })
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'Could not change password.')
    }
  })
  return (
    <form
      onSubmit={(event) => void submit(event)}
      className="card border border-base-300 bg-base-100"
    >
      <div className="card-body gap-5 p-5 sm:p-6">
        <fieldset className="fieldset min-w-0 gap-5 p-0 text-sm" disabled={isSubmitting}>
          <legend className="fieldset-legend pt-0 pb-5 text-base">Change password</legend>
          <div className="grid gap-5 sm:grid-cols-2">
            <label className="flex flex-col gap-2">
              Current password
              <input
                className="input w-full"
                type="password"
                autoComplete="current-password"
                minLength={12}
                maxLength={128}
                required
                {...register('current_password')}
              />
            </label>
            <label className="flex flex-col gap-2">
              New password
              <input
                className="input w-full"
                type="password"
                autoComplete="new-password"
                minLength={12}
                maxLength={128}
                required
                {...register('new_password')}
              />
            </label>
          </div>
          <p className="text-xs text-base-content/70">
            Changing your password signs out all devices.
          </p>
          <div className="border-t border-base-300 pt-5">
            <button className="btn btn-sm" type="submit">
              {isSubmitting ? 'Changing…' : 'Change password'}
            </button>
          </div>
        </fieldset>
        {error && (
          <div role="alert" className="alert alert-soft alert-error">
            {error}
          </div>
        )}
      </div>
    </form>
  )
}

function SettingsPage() {
  const account = useSyncExternalStore(subscribeAccount, currentAccount)
  const settings = useQuery({
    queryKey: settingsKey,
    queryFn: () => accountRequest<ModelSettings>('/settings/models'),
  })
  const usage = useQuery({
    queryKey: ['model-usage'],
    queryFn: () => accountRequest<Usage>('/settings/usage'),
  })
  const [error, setError] = useState('')
  const router = useRouter()
  const [loggingOut, setLoggingOut] = useState(false)
  const logout = async () => {
    setLoggingOut(true)
    setError('')
    try {
      await accountRequest('/auth/logout', 'POST')
      changeAccount(null)
      await router.navigate({ to: '/login' })
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'Could not sign out.')
    }
    setLoggingOut(false)
  }
  return (
    <section className="mx-auto w-full max-w-2xl py-2 sm:py-4">
      <PageHeading title="Settings">
        <button
          className="btn text-sm font-medium btn-error [--btn-color:color-mix(in_oklab,var(--color-error),var(--color-base-content)_30%)] [--btn-fg:var(--color-base-100)] text-shadow-none"
          type="button"
          disabled={loggingOut}
          onClick={() => void logout()}
        >
          {loggingOut ? 'Signing out…' : 'Sign out'}
        </button>
      </PageHeading>
      <p className="mb-5 text-base-content/70">Signed in as {account?.username}.</p>
      {usage.data && (
        <section
          aria-labelledby="usage-heading"
          className="card mb-8 border border-base-300 bg-base-100"
        >
          <div className="card-body gap-5 p-5 sm:p-6">
            <h2 id="usage-heading" className="card-title text-base">
              Daily server allowance
            </h2>
            <dl className="grid min-w-0 gap-5 sm:grid-cols-2">
              <div className="min-w-0 space-y-2">
                <dt className="flex items-center gap-2 text-sm text-base-content/70">
                  <Icon name="sparkles" size={18} className="shrink-0" />
                  Your remaining operations
                </dt>
                <dd className="text-3xl font-semibold tabular-nums">
                  {usage.data.remaining}
                  <span className="text-base font-normal text-base-content/70">
                    {' '}
                    / {usage.data.limit}
                  </span>
                </dd>
              </div>
              <div className="min-w-0 space-y-2 border-t border-base-300 pt-5 sm:border-t-0 sm:border-l sm:pt-0 sm:pl-5">
                <dt className="flex items-center gap-2 text-sm text-base-content/70">
                  <Icon name="server" size={18} className="shrink-0" />
                  Site remaining operations
                </dt>
                <dd className="text-3xl font-semibold tabular-nums">
                  {usage.data.server_remaining}
                </dd>
              </div>
            </dl>
            <div className="border-t border-base-300 pt-5 text-xs text-base-content/70">
              <p className="flex items-center gap-2">
                <Icon name="clock" size={16} className="shrink-0" />
                Resets at midnight in Hong Kong
              </p>
            </div>
          </div>
        </section>
      )}
      {(error || settings.error || usage.error) && (
        <div role="alert" className="mb-5 alert alert-soft alert-error">
          {error || settings.error?.message || usage.error?.message}
          <button
            type="button"
            className="btn btn-sm"
            onClick={() => {
              void settings.refetch()
              void usage.refetch()
            }}
          >
            Retry
          </button>
        </div>
      )}
      {settings.isPending && <output>Loading settings…</output>}
      {settings.data && (
        <div className="space-y-8">
          <section aria-labelledby="models-heading" className="space-y-4">
            <h2 id="models-heading" className="text-sm font-semibold text-base-content/70">
              Model configuration
            </h2>
            {!settings.data.personal_available && (
              <p>Personal model settings are unavailable. Contact the site owner.</p>
            )}
            {(['semantic', 'decision'] as const).map((role) => (
              <ModelForm
                key={`${role}:${settings.data.roles[role].personal}:${settings.data.roles[role].endpoint_id}:${settings.data.roles[role].model}:${settings.data.roles[role].thinking}`}
                role={role}
                info={settings.data.roles[role]}
                settings={settings.data}
              />
            ))}
          </section>
          <section aria-labelledby="security-heading" className="space-y-4">
            <h2 id="security-heading" className="text-sm font-semibold text-base-content/70">
              Account security
            </h2>
            <PasswordForm />
          </section>
        </div>
      )}
    </section>
  )
}
