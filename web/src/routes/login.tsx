import { createFileRoute, Link, useRouter } from '@tanstack/react-router'
import { useState } from 'react'
import { useForm } from 'react-hook-form'

import { Icon } from '../components/icon'
import { accountRequest, changeAccount, type Account } from '../lib/auth-client'
import { GITHUB_URL } from '../lib/project-links'

export const Route = createFileRoute('/login')({ component: LoginPage })

interface LoginFields {
  username: string
  password: string
}

function LoginPage() {
  const [registering, setRegistering] = useState(false)
  const [error, setError] = useState('')
  const router = useRouter()
  const {
    register,
    handleSubmit,
    reset,
    formState: { isSubmitting },
  } = useForm<LoginFields>()
  const submit = handleSubmit(async (values) => {
    setError('')
    try {
      const account = await accountRequest<Account>(
        registering ? '/auth/register' : '/auth/login',
        'POST',
        {
          username: values.username,
          password: values.password,
        },
      )
      reset()
      changeAccount(account)
      await router.navigate({ to: '/new' })
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'Could not sign in. Try again.')
    }
  })
  return (
    <main className="flex min-h-dvh items-center justify-center bg-base-200/25 px-5 py-8 sm:py-12">
      <div className="w-full max-w-sm">
        <Link
          to="/"
          className="mb-5 flex w-fit items-center gap-2.5 text-xl font-bold tracking-tight"
        >
          <span className="flex size-9 items-center justify-center rounded-box bg-primary/55 text-primary-content">
            <Icon name="compass" size={24} />
          </span>
          <span>
            JobScout<span className="text-primary-content">.</span>
          </span>
        </Link>
        <h1 className="sr-only">{registering ? 'Register' : 'Sign in'}</h1>
        <form onSubmit={(event) => void submit(event)} className="space-y-5 sm:space-y-6">
          <div className="card border border-base-300 bg-base-100">
            <div className="card-body gap-5 p-5 sm:gap-6 sm:p-6">
              <fieldset disabled={isSubmitting} className="fieldset min-w-0 gap-4 p-0 text-sm">
                <legend className="sr-only">Account details</legend>
                <label className="flex flex-col gap-2">
                  Username
                  <input
                    className="input w-full"
                    autoComplete="username"
                    minLength={3}
                    maxLength={32}
                    pattern="[a-zA-Z0-9_.-]+"
                    required
                    {...register('username')}
                  />
                </label>
                <label className="flex flex-col gap-2">
                  Password
                  <input
                    className="input w-full"
                    type="password"
                    autoComplete={registering ? 'new-password' : 'current-password'}
                    minLength={12}
                    maxLength={128}
                    aria-describedby={registering ? 'password-help' : undefined}
                    required
                    {...register('password')}
                  />
                  {registering && (
                    <span id="password-help" className="text-xs text-base-content/70">
                      Use 12–128 characters.
                    </span>
                  )}
                </label>
              </fieldset>
              {error && (
                <div role="alert" className="alert alert-soft alert-error">
                  {error}
                </div>
              )}
              <button className="btn btn-primary" type="submit" disabled={isSubmitting}>
                {isSubmitting ? 'Please wait…' : registering ? 'Create account' : 'Sign in'}
              </button>
            </div>
          </div>
          <div className="text-center">
            <button
              className="btn h-auto min-h-8 max-w-full btn-ghost px-2 font-normal whitespace-normal btn-sm"
              type="button"
              disabled={isSubmitting}
              onClick={() => {
                setRegistering(!registering)
                setError('')
                reset()
              }}
            >
              {registering ? 'Already have an account? Sign in' : 'New here? Create an account'}
            </button>
          </div>
        </form>
        <div className="mt-5 text-center">
          <a
            href={GITHUB_URL}
            target="_blank"
            rel="noopener noreferrer"
            aria-label="View on GitHub (opens in a new tab)"
            className="inline-flex link items-center gap-2 text-sm text-base-content/60 link-hover hover:text-base-content"
          >
            <Icon name="github" size={16} />
            View on GitHub
          </a>
        </div>
      </div>
    </main>
  )
}
