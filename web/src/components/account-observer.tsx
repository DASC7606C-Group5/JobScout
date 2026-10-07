import { useRouter } from '@tanstack/react-router'
import { useEffect, useSyncExternalStore } from 'react'

import { changeAccount, currentAccount, identityEvents, subscribeAccount } from '../lib/auth-client'
import { clearNotifications } from '../state/notifications'

export function AccountObserver() {
  const router = useRouter()
  const account = useSyncExternalStore(subscribeAccount, currentAccount)
  useEffect(() => {
    if (!account) return
    const timer = setTimeout(
      () => changeAccount(null),
      Math.max(0, Date.parse(account.expires_at) - Date.now()),
    )
    return () => clearTimeout(timer)
  }, [account])
  useEffect(() => {
    const changed = () => {
      clearNotifications()
      if (!currentAccount()) void router.navigate({ to: '/login' })
      void router.invalidate()
    }
    identityEvents.addEventListener('change', changed)
    return () => identityEvents.removeEventListener('change', changed)
  }, [router])
  return null
}
