// Decides once, before the first render, whether the UI talks to the API or to the bundled demo data.
// VITE_DEMO=1 or ?demo=1 forces demo data; VITE_DEMO=0 or ?demo=0 forces the API. Otherwise the API is
// used when /api/health answers, and the demo data when it doesn't (this repository does not include the meeting API yet).
import { API_BASE } from "./base";

let demo = false;

export function isDemo(): boolean {
  return demo;
}

function forced(): boolean | null {
  const q = new URLSearchParams(window.location.search).get("demo");
  const env = import.meta.env.VITE_DEMO as string | undefined;
  const v = q ?? env;
  if (v === "1" || v === "true") return true;
  if (v === "0" || v === "false") return false;
  return null;
}

export async function resolveMode(): Promise<boolean> {
  const f = forced();
  if (f !== null) return (demo = f);
  try {
    const res = await fetch(`${API_BASE}/api/health`, { signal: AbortSignal.timeout(2500) });
    const body = res.ok ? ((await res.json()) as { ok?: unknown }) : null;
    demo = !body || typeof body.ok !== "boolean";
  } catch {
    demo = true;
  }
  return demo;
}
