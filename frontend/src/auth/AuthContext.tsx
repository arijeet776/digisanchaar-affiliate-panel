import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { api, ApiError, registerSessionExpiredHandler } from "../api/client";
import { clearTokens, getRefreshToken, setAccessToken, setRefreshToken } from "../api/tokenStore";

export type Role = "super_admin" | "manager" | "publisher";

interface CurrentUser {
  user_id: string;
  role: Role;
  account_status: string;
}

interface AuthContextValue {
  user: CurrentUser | null;
  loading: boolean;
  error: string | null;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function loadCurrentUser(): Promise<void> {
    try {
      const { data } = await api.get<CurrentUser>("/auth/me");
      setUser(data);
    } catch {
      setUser(null);
    }
  }

  async function logout(): Promise<void> {
    const refreshToken = getRefreshToken();
    if (refreshToken) {
      try {
        await api.post("/auth/logout", { refresh_token: refreshToken });
      } catch {
        /* best-effort — clear local state regardless */
      }
    }
    clearTokens();
    setUser(null);
  }

  useEffect(() => {
    registerSessionExpiredHandler(() => {
      setUser(null);
    });

    // Hydrate: if a refresh token survived a reload, exchange it for a
    // fresh access token, then load the current (DB-authoritative) user.
    (async () => {
      const refreshToken = getRefreshToken();
      if (!refreshToken) {
        setLoading(false);
        return;
      }
      try {
        const { data } = await api.post<{ access_token: string; refresh_token: string }>("/auth/refresh", {
          refresh_token: refreshToken,
        });
        setAccessToken(data.access_token);
        setRefreshToken(data.refresh_token);
        await loadCurrentUser();
      } catch {
        clearTokens();
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  async function login(email: string, password: string): Promise<void> {
    setError(null);
    try {
      const { data } = await api.post<{ access_token: string; refresh_token: string }>("/auth/login", {
        email,
        password,
      });
      setAccessToken(data.access_token);
      setRefreshToken(data.refresh_token);
      await loadCurrentUser();
    } catch (e) {
      const message = e instanceof ApiError ? e.message : "Unable to log in. Please try again.";
      setError(message);
      throw e;
    }
  }

  return (
    <AuthContext.Provider value={{ user, loading, error, login, logout }}>{children}</AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
