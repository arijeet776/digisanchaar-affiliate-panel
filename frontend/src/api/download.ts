import { getAccessToken } from "./tokenStore";

/** Authenticated file download (the Export Center file lives behind the API). */
export async function downloadAuthed(path: string, fallbackName: string): Promise<void> {
  const token = getAccessToken();
  const base = (import.meta.env.VITE_API_BASE_URL || "/api/v1").replace(/\/$/, "");
  const res = await fetch(`${base}${path}`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  if (!res.ok) throw new Error(`Download failed (${res.status})`);
  const cd = res.headers.get("Content-Disposition") ?? "";
  const name = /filename="?([^";]+)"?/.exec(cd)?.[1] ?? fallbackName;
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
