import { createContext, useContext, useEffect, useEffectEvent } from 'react'
import { toast } from 'sonner'

type NotificationAction =
  | { label: string; onClick: () => unknown; href?: never }
  | { label: string; href: string; onClick?: never }

export interface Notification {
  id: string
  message: string
  tone: 'error' | 'warning'
  actions?: NotificationAction[] | undefined
  duration?: number
}

export const NotificationContext = createContext<{
  notify: (notification: Notification) => void
  dismiss: (id: string) => void
} | null>(null)

export function useNotifications() {
  const context = useContext(NotificationContext)
  if (!context) throw new Error('NotificationProvider is required')
  return context
}

export function useNotification(trigger: unknown, notification: Notification) {
  const { notify, dismiss } = useNotifications()
  const { id } = notification
  const announce = useEffectEvent(() => notify(notification))
  useEffect(() => {
    if (trigger) announce()
    else dismiss(id)
    return () => dismiss(id)
  }, [trigger, id, dismiss])
}
export const pendingActions = new Set<string>()
export const pendingDismissals = new Set<string>()

export function clearNotifications() {
  toast.dismiss()
  pendingActions.clear()
  pendingDismissals.clear()
}
