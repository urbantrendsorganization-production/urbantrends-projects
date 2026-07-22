"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";

import { PUBLIC_API_BASE } from "@/lib/config";
import type { Me } from "@/lib/types";

const ACCESS_KEY = "mkt.access";
const REFRESH_KEY = "mkt.refresh";

type RegisterInput = {
  email: string;
  password: string;
  display_name?: string;
};

type AuthState = {
  user: Me | null;
  loading: boolean;
  isAuthenticated: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (input: RegisterInput) => Promise<{ detail: string }>;
  logout: () => void;
  refreshUser: () => Promise<void>;
  // Fetch an API path with the access token attached, refreshing once on 401.
  authFetch: (path: string, init?: RequestInit) => Promise<Response>;
};

const AuthContext = createContext<AuthState | null>(null);

const url = (path: string) => `${PUBLIC_API_BASE}${path}`;

/** Pull a human-readable message out of the {detail, code} error envelope. */
function flattenError(data: unknown, fallback = "Something went wrong."): string {
  const detail = (data as { detail?: unknown })?.detail ?? data;
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object") {
    const first = Object.values(detail as Record<string, unknown>)[0];
    if (Array.isArray(first)) return String(first[0]);
    if (first != null) return String(first);
  }
  return fallback;
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);

  const setTokens = (access?: string, refresh?: string) => {
    if (access) localStorage.setItem(ACCESS_KEY, access);
    if (refresh) localStorage.setItem(REFRESH_KEY, refresh);
  };
  const clearTokens = () => {
    localStorage.removeItem(ACCESS_KEY);
    localStorage.removeItem(REFRESH_KEY);
  };

  const tryRefresh = useCallback(async (): Promise<string | null> => {
    const refresh = localStorage.getItem(REFRESH_KEY);
    if (!refresh) return null;
    const res = await fetch(url("/api/v1/auth/refresh/"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh }),
    });
    if (!res.ok) {
      clearTokens();
      return null;
    }
    const data = await res.json();
    setTokens(data.access, data.refresh); // rotation issues a new refresh too
    return data.access as string;
  }, []);

  const authFetch = useCallback(
    async (path: string, init: RequestInit = {}) => {
      const call = (token: string | null) =>
        fetch(url(path), {
          ...init,
          headers: {
            ...(init.headers ?? {}),
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
        });

      let res = await call(localStorage.getItem(ACCESS_KEY));
      if (res.status === 401) {
        const refreshed = await tryRefresh();
        if (refreshed) res = await call(refreshed);
      }
      return res;
    },
    [tryRefresh],
  );

  const refreshUser = useCallback(async () => {
    const res = await authFetch("/api/v1/users/me/");
    setUser(res.ok ? ((await res.json()) as Me) : null);
  }, [authFetch]);

  // Hydrate the session from a stored token on first load.
  useEffect(() => {
    (async () => {
      if (localStorage.getItem(ACCESS_KEY) || localStorage.getItem(REFRESH_KEY)) {
        await refreshUser();
      }
      setLoading(false);
    })();
  }, [refreshUser]);

  const login = useCallback(
    async (email: string, password: string) => {
      const res = await fetch(url("/api/v1/auth/login/"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      if (!res.ok) {
        throw new Error(
          flattenError(await res.json().catch(() => ({})), "Invalid email or password."),
        );
      }
      const data = await res.json();
      setTokens(data.access, data.refresh);
      await refreshUser();
    },
    [refreshUser],
  );

  const register = useCallback(async (input: RegisterInput) => {
    const res = await fetch(url("/api/v1/auth/register/"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(flattenError(data));
    return data as { detail: string };
  }, []);

  const logout = useCallback(() => {
    clearTokens();
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider
      value={{
        user,
        loading,
        isAuthenticated: !!user,
        login,
        register,
        logout,
        refreshUser,
        authFetch,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider");
  return ctx;
}
