// Light ("studio daylight", the default) or dark ("night session"). The choice lives on <html data-theme> and in
// localStorage; index.html applies it before the first paint so the page never flashes the wrong theme.
import { useSyncExternalStore } from "react";

export type Theme = "light" | "dark";

const KEY = "onrecord-theme";
const EVENT = "wsw:theme";
const META: Record<Theme, string> = { light: "#f6f5f2", dark: "#08090b" };

export function currentTheme(): Theme {
  return document.documentElement.dataset.theme === "dark" ? "dark" : "light";
}

export function setTheme(theme: Theme): void {
  const root = document.documentElement;
  if (theme === "dark") root.dataset.theme = "dark";
  else delete root.dataset.theme;
  try {
    localStorage.setItem(KEY, theme);
  } catch {
    // private mode: the choice lasts for this page only
  }
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", META[theme]);
  window.dispatchEvent(new CustomEvent<Theme>(EVENT, { detail: theme }));
}

export function toggleTheme(): void {
  setTheme(currentTheme() === "dark" ? "light" : "dark");
}

/** Calls back after the theme changes, once the new tokens are in effect (canvases re-read their colours here). */
export function onThemeChange(cb: (theme: Theme) => void): () => void {
  const on = (e: Event) => cb((e as CustomEvent<Theme>).detail);
  window.addEventListener(EVENT, on);
  return () => window.removeEventListener(EVENT, on);
}

export function useTheme(): Theme {
  return useSyncExternalStore(onThemeChange, currentTheme, () => "light");
}
