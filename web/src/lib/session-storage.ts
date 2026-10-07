import { currentAccount } from './auth-client'

function sessionIdKey() {
  return `jobscout.session_id.${currentAccount()?.user_id ?? 'signed-out'}`
}

export function readSessionId(): string | null {
  try {
    return localStorage.getItem(sessionIdKey())
  } catch {
    return null
  }
}

export function rememberSessionId(sessionId: string | null) {
  try {
    if (sessionId) localStorage.setItem(sessionIdKey(), sessionId)
    else localStorage.removeItem(sessionIdKey())
  } catch {
    // The route remains usable when browser preferences cannot be stored.
  }
}
