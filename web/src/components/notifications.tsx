import { useEffect, useRef, type ReactNode } from 'react'
import { toast, Toaster, useSonner } from 'sonner'

import { NotificationContext, type Notification } from '../state/notifications'
import { AsyncButton } from './async-button'
import { Icon } from './icon'

const pendingActions = new Set<string>()
const pendingDismissals = new Set<string>()

function notify(notification: Notification) {
  pendingDismissals.delete(notification.id)
  toast.custom(
    (id) => (
      <div
        role="alert"
        className={`alert w-full items-start alert-soft text-sm shadow-lg ${notification.tone === 'error' ? 'alert-error' : 'alert-warning'}`}
      >
        <Icon name="info" size={19} />
        <div className="min-w-0">
          <p className="wrap-anywhere">{notification.message}</p>
          {notification.actions && (
            <div className="mt-3 flex flex-wrap gap-2">
              {notification.actions.map((action) =>
                action.href ? (
                  <a
                    key={action.label}
                    href={action.href}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="btn btn-sm"
                  >
                    {action.label}
                  </a>
                ) : (
                  <AsyncButton
                    key={action.label}
                    type="button"
                    className="btn btn-sm"
                    onClick={async () => {
                      // Keep the action visible while the request is pending.
                      pendingActions.add(notification.id)
                      try {
                        const result = await action.onClick?.()
                        const failed =
                          result === false ||
                          (result &&
                            typeof result === 'object' &&
                            'isError' in result &&
                            result.isError)
                        if (!failed) toast.dismiss(id)
                      } finally {
                        pendingActions.delete(notification.id)
                        if (pendingDismissals.delete(notification.id)) toast.dismiss(id)
                      }
                    }}
                  >
                    {action.label}
                  </AsyncButton>
                ),
              )}
            </div>
          )}
        </div>
        <button
          type="button"
          className="btn btn-square btn-ghost btn-xs"
          aria-label="Dismiss notification"
          onClick={() => toast.dismiss(id)}
        >
          <Icon name="close" size={16} />
        </button>
      </div>
    ),
    {
      id: notification.id,
      duration: notification.duration ?? (notification.tone === 'error' ? Infinity : 8000),
    },
  )
}

const dismiss = (id: string) => {
  if (pendingActions.has(id)) pendingDismissals.add(id)
  else toast.dismiss(id)
}

export function NotificationProvider({ children }: { children: ReactNode }) {
  return (
    <NotificationContext
      value={{
        notify,
        dismiss,
      }}
    >
      {children}
      <NotificationViewport />
    </NotificationContext>
  )
}

function NotificationViewport() {
  const { toasts } = useSonner()
  const viewport = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const element = viewport.current
    if (!element) return
    // Keep recovery actions above native modal dialogs in the browser's top layer.
    element.hidePopover()
    if (toasts.length) element.showPopover()
  }, [toasts])
  return (
    <div ref={viewport} popover="manual" className="m-0 border-0 bg-transparent p-0">
      <Toaster
        position="top-right"
        expand
        visibleToasts={3}
        offset={24}
        mobileOffset={16}
        style={{ fontFamily: 'inherit' }}
      />
    </div>
  )
}
