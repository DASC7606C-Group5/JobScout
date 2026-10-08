import { useQuery, useQueryClient } from '@tanstack/react-query'
import { createFileRoute, useRouter } from '@tanstack/react-router'
import { useRef, useState, useSyncExternalStore } from 'react'
import { useForm, useWatch } from 'react-hook-form'

import type { ModelInfo, ModelSettingsResponse } from '../api/types.gen'
import { Icon } from '../components/icon'
import { PageHeading } from '../components/layout/page-heading'
import { accountClient, changeAccount, currentAccount, subscribeAccount } from '../lib/auth-client'

export const Route = createFileRoute('/_workspace/settings')({ component: SettingsPage })
type Role = 'semantic' | 'decision'
interface ModelFields {
  endpoint_id: string
  model: string
  api_key: string
  thinking: boolean
  thinking_level: string
}
const settingsKey = ['model-settings'] as const

interface ModelFormProps {
  role: Role
  info: ModelInfo
  settings: ModelSettingsResponse
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
      thinking_level: info.personal && info.thinking ? info.thinking_level : 'high',
    },
  })
  const endpoint = useWatch({ control, name: 'endpoint_id' })
  const thinking = useWatch({ control, name: 'thinking' })
  const thinkingSupported =
    settings.endpoints.find((item) => item.id === endpoint)?.thinking_supported ?? false
  const thinkingLevelSupported =
    settings.endpoints.find((item) => item.id === endpoint)?.thinking_level_supported ?? false
  const save = handleSubmit(async (values) => {
    setMessage('')
    setError('')
    try {
      if (values.endpoint_id === 'server') await accountClient.clearModel(role)
      else
        await accountClient.saveModel(role, {
          endpoint_id: values.endpoint_id,
          model: values.model.trim(),
          thinking: thinkingSupported && values.thinking,
          thinking_level: values.thinking_level.trim() || 'high',
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
      await accountClient.testModel(role)
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
    thinking,
    thinkingSupported,
    thinkingLevelSupported,
    save,
    test,
    message,
    error,
  }
}

function ConnectionTestButton({
  endpoint,
  info,
  testing,
  test,
}: {
  endpoint: string
  info: ModelInfo
  testing: boolean
  test: () => Promise<void>
}) {
  if (endpoint === 'server') return null
  return (
    <button
      className="btn btn-ghost btn-sm"
      type="button"
      disabled={!info.personal || endpoint !== info.endpoint_id || !info.key_configured}
      onClick={() => void test()}
    >
      {testing ? 'Testing…' : 'Test'}
    </button>
  )
}

function ModelForm({ role, info, settings }: ModelFormProps) {
  const {
    register,
    isSubmitting,
    testing,
    endpoint,
    thinking,
    thinkingSupported,
    thinkingLevelSupported,
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
      <div className="card-body gap-5 p-5 sm:gap-6 sm:p-6">
        <fieldset
          disabled={isSubmitting || testing}
          className="fieldset min-w-0 gap-5 p-0 text-sm sm:gap-6"
        >
          <legend className="fieldset-legend w-full justify-start gap-2 pt-0 pb-5 text-base whitespace-normal sm:pb-6">
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
              <dd>{info.server_thinking ? 'true' : 'false'}</dd>
              {info.server_provider !== 'openai_compatible' && info.server_thinking && (
                <>
                  <dt className="text-base-content/70">Reasoning effort</dt>
                  <dd>{info.server_thinking_level}</dd>
                </>
              )}
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
                    Thinking mode
                  </label>
                </div>
              )}
              {thinkingLevelSupported && thinking && (
                <label className="flex flex-col gap-2">
                  Reasoning effort
                  <input
                    className="input w-full"
                    maxLength={32}
                    placeholder="low, medium, high, max, ..."
                    {...register('thinking_level')}
                  />
                </label>
              )}
            </>
          )}
          {error && (
            <div role="alert" className="alert alert-soft alert-error">
              {error}
            </div>
          )}
          <div className="-mx-5 flex flex-wrap items-center gap-3 border-t border-base-300 px-5 pt-5 sm:-mx-6 sm:px-6 sm:pt-6">
            <button className="btn btn-sm" type="submit">
              {isSubmitting ? 'Saving…' : 'Save configuration'}
            </button>
            <ConnectionTestButton endpoint={endpoint} info={info} testing={testing} test={test} />
            {message && (
              <output className="flex items-center gap-1.5 text-xs text-base-content/70">
                <Icon name="check" size={16} className="shrink-0" />
                {message}
              </output>
            )}
          </div>
        </fieldset>
      </div>
    </form>
  )
}

function DeleteAccountCard() {
  const router = useRouter()
  const dialog = useRef<HTMLDialogElement>(null)
  const cancel = useRef<HTMLButtonElement>(null)
  const [deleting, setDeleting] = useState(false)
  const [error, setError] = useState('')

  async function confirmDelete() {
    if (deleting) return
    setDeleting(true)
    setError('')
    try {
      await accountClient.deleteAccount()
      dialog.current?.close()
      changeAccount(null)
      await router.navigate({ to: '/login' })
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'Could not delete account.')
    } finally {
      setDeleting(false)
    }
  }

  return (
    <section
      className="card border border-base-300 bg-base-100"
      aria-labelledby="delete-account-heading"
    >
      <div className="card-body gap-5 p-5 sm:gap-6 sm:p-6">
        <h3 id="delete-account-heading" className="card-title text-base">
          Delete account
        </h3>
        <p className="text-sm text-base-content/70">
          Permanently delete your account and saved data.
        </p>
        <div className="-mx-5 border-t border-base-300 px-5 pt-5 sm:-mx-6 sm:px-6 sm:pt-6">
          <button
            type="button"
            className="btn btn-soft btn-error btn-sm"
            onClick={() => {
              setError('')
              dialog.current?.showModal()
              cancel.current?.focus()
            }}
          >
            Delete account
          </button>
        </div>
      </div>
      <dialog
        ref={dialog}
        className="modal"
        aria-labelledby="delete-account-title"
        aria-describedby="delete-account-consequence"
        onCancel={(event) => {
          if (deleting) event.preventDefault()
        }}
      >
        <div className="modal-box">
          <h2 id="delete-account-title" className="text-base font-semibold">
            Delete account?
          </h2>
          <p
            id="delete-account-consequence"
            className="mt-2 text-sm leading-6 text-base-content/70"
          >
            Your searches, resumes, saved jobs and model settings will be permanently deleted. This
            cannot be undone.
          </p>
          {error && (
            <div role="alert" className="mt-4 alert alert-soft alert-error">
              {error}
            </div>
          )}
          <form method="dialog" className="modal-action">
            <button ref={cancel} type="submit" className="btn btn-ghost" disabled={deleting}>
              Keep account
            </button>
            <button
              type="button"
              className="btn btn-error"
              disabled={deleting}
              aria-busy={deleting}
              onClick={() => void confirmDelete()}
            >
              {deleting ? 'Deleting…' : 'Delete account'}
            </button>
          </form>
        </div>
      </dialog>
    </section>
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
      await accountClient.changePassword(values)
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
      <div className="card-body gap-5 p-5 sm:gap-6 sm:p-6">
        <fieldset className="fieldset min-w-0 gap-5 p-0 text-sm sm:gap-6" disabled={isSubmitting}>
          <legend className="fieldset-legend pt-0 pb-5 text-base sm:pb-6">Change password</legend>
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
          {error && (
            <div role="alert" className="alert alert-soft alert-error">
              {error}
            </div>
          )}
          <div className="-mx-5 border-t border-base-300 px-5 pt-5 sm:-mx-6 sm:px-6 sm:pt-6">
            <button className="btn btn-sm" type="submit">
              {isSubmitting ? 'Changing…' : 'Change password'}
            </button>
          </div>
        </fieldset>
      </div>
    </form>
  )
}

function SettingsPage() {
  const account = useSyncExternalStore(subscribeAccount, currentAccount)
  const settings = useQuery({
    queryKey: settingsKey,
    queryFn: ({ signal }) => accountClient.models(signal),
  })
  const usage = useQuery({
    queryKey: ['model-usage'],
    queryFn: ({ signal }) => accountClient.usage(signal),
  })
  const [error, setError] = useState('')
  const router = useRouter()
  const [loggingOut, setLoggingOut] = useState(false)
  const logout = async () => {
    setLoggingOut(true)
    setError('')
    try {
      await accountClient.logout()
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
          className="btn text-sm font-medium btn-error"
          type="button"
          disabled={loggingOut}
          onClick={() => void logout()}
        >
          {loggingOut ? 'Signing out…' : 'Sign out'}
        </button>
      </PageHeading>
      <p className="mb-5 text-base-content/70">Signed in as {account?.username}.</p>
      {usage.data?.enabled && (
        <section
          aria-labelledby="usage-heading"
          className="card mb-8 border border-base-300 bg-base-100"
        >
          <div className="card-body gap-5 p-5 sm:gap-6 sm:p-6">
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
              <div className="-mx-5 min-w-0 space-y-2 border-t border-base-300 px-5 pt-5 sm:mx-0 sm:border-t-0 sm:border-l sm:px-0 sm:pt-0 sm:pl-5">
                <dt className="flex items-center gap-2 text-sm text-base-content/70">
                  <Icon name="server" size={18} className="shrink-0" />
                  Site remaining operations
                </dt>
                <dd className="text-3xl font-semibold tabular-nums">
                  {usage.data.server_remaining}
                </dd>
              </div>
            </dl>
            <div className="-mx-5 border-t border-base-300 px-5 pt-5 text-xs text-base-content/70 sm:-mx-6 sm:px-6 sm:pt-6">
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
                key={`${role}:${settings.data.roles[role].personal}:${settings.data.roles[role].endpoint_id}:${settings.data.roles[role].model}:${settings.data.roles[role].thinking}:${settings.data.roles[role].thinking_level}`}
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
            <DeleteAccountCard />
          </section>
        </div>
      )}
    </section>
  )
}
