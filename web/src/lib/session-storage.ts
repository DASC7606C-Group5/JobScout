const SESSION_ID_KEY = 'jobscout.session_id'

export function readSessionId(): string | null {
  try {
    const current = localStorage.getItem(SESSION_ID_KEY)
    const previous = sessionStorage.getItem(SESSION_ID_KEY)
    if (!current && previous) localStorage.setItem(SESSION_ID_KEY, previous)
    sessionStorage.removeItem(SESSION_ID_KEY)
    return current ?? previous
  } catch {
    return null
  }
}

export function rememberSessionId(sessionId: string | null) {
  try {
    if (sessionId) localStorage.setItem(SESSION_ID_KEY, sessionId)
    else localStorage.removeItem(SESSION_ID_KEY)
  } catch {
    // The route remains usable when browser preferences cannot be stored.
  }
}
