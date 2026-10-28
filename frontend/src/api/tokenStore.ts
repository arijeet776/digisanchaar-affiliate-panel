/**
 * Token storage tradeoff (documented, not silently decided): the access
 * token lives in memory ONLY — never persisted, gone on tab close/reload,
 * which limits an XSS payload's ability to exfiltrate it long-term. The
 * refresh token is persisted in localStorage so the session survives a
 * page reload without forcing a fresh login every time, which the existing
 * backend contract (Part 2's POST /auth/refresh takes a JSON body, not a
 * cookie) requires the client to hold onto somewhere. A more hardened
 * setup — httpOnly refresh cookie — would remove localStorage entirely;
 * that's a reasonable Part 11 (security hardening) follow-up, not
 * something this foundation silently claims to already do.
 */
const REFRESH_KEY = "qx-refresh-token";

let accessToken: string | null = null;

export function getAccessToken(): string | null {
  return accessToken;
}

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export function getRefreshToken(): string | null {
  return localStorage.getItem(REFRESH_KEY);
}

export function setRefreshToken(token: string | null): void {
  if (token) localStorage.setItem(REFRESH_KEY, token);
  else localStorage.removeItem(REFRESH_KEY);
}

export function clearTokens(): void {
  accessToken = null;
  setRefreshToken(null);
}
