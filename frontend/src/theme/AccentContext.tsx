import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api } from "../api/client";

/**
 * Global accent theme (Part 16.2). Independent of light/dark mode:
 * <html data-theme="dark|light"> is owned by ThemeContext, while
 * <html data-accent="..."> is owned here and set platform-wide by the Super
 * Admin. The server value is authoritative; localStorage is only a first-paint
 * cache (mirrored by the inline script in index.html).
 */
export type AccentId = "deep-yellow" | "deep-sky" | "deep-orange" | "hasmind-purple";

export const DEFAULT_ACCENT: AccentId = "deep-yellow";

export const ACCENT_OPTIONS: { id: AccentId; label: string; swatch: string }[] = [
  { id: "deep-yellow", label: "Deep Yellow", swatch: "linear-gradient(135deg, #f2b705, #d68a00)" },
  { id: "deep-sky", label: "Deep Sky Blue", swatch: "linear-gradient(135deg, #0a7cb8, #2b6fe3)" },
  { id: "deep-orange", label: "Deep Orange", swatch: "linear-gradient(135deg, #f2680f, #d4440c)" },
  { id: "hasmind-purple", label: "Hasmind Purple", swatch: "linear-gradient(135deg, #9a4cf0, #7a22e6)" },
];

const STORAGE_KEY = "qx-accent";

export function isAccentId(v: unknown): v is AccentId {
  return typeof v === "string" && ACCENT_OPTIONS.some((o) => o.id === v);
}

function readInitial(): AccentId {
  const attr = document.documentElement.getAttribute("data-accent");
  return isAccentId(attr) ? attr : DEFAULT_ACCENT;
}

interface AccentContextValue {
  accent: AccentId;
  /** Apply a value that the server has already accepted (after a successful save). */
  applyAccent: (a: AccentId) => void;
}

const AccentContext = createContext<AccentContextValue | undefined>(undefined);

export function AccentProvider({ children }: { children: ReactNode }) {
  const [accent, setAccent] = useState<AccentId>(readInitial);

  useEffect(() => {
    document.documentElement.setAttribute("data-accent", accent);
    try {
      localStorage.setItem(STORAGE_KEY, accent);
    } catch {
      /* storage unavailable - the server value still applies */
    }
  }, [accent]);

  const refresh = useCallback(() => {
    api
      .get<{ accent_theme: string }>("/appearance")
      .then((r) => {
        if (isAccentId(r.data?.accent_theme)) setAccent(r.data.accent_theme);
      })
      .catch(() => {
        /* keep cached/default accent; appearance must never block the app */
      });
  }, []);

  useEffect(() => {
    refresh();
    const onVisible = () => {
      if (document.visibilityState === "visible") refresh();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [refresh]);

  return <AccentContext.Provider value={{ accent, applyAccent: setAccent }}>{children}</AccentContext.Provider>;
}

export function useAccent(): AccentContextValue {
  const ctx = useContext(AccentContext);
  if (!ctx) throw new Error("useAccent must be used within AccentProvider");
  return ctx;
}
