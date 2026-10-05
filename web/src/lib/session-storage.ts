const SESSION_ID_KEY = 'jobscout.session_id'

export function readSessionId(): string | null {
  try {
    return sessionStorage.getItem(SESSION_ID_KEY)
  } catch {
    return null
  }
}

export function rememberSessionId(sessionId: string | null) {
  try {
    if (sessionId) sessionStorage.setItem(SESSION_ID_KEY, sessionId)
    else sessionStorage.removeItem(SESSION_ID_KEY)
  } catch {
    // Browsers with storage disabled can still use the current in-memory session.
  }
}
