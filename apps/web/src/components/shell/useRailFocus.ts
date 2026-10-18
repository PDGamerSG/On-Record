// Keeps keyboard focus on screen while the desktop rail opens. The dock's buttons are hidden once the rail is open, so
// the focused "Open navigation" button disappears and focus would fall to the page body.
import { useEffect, useRef } from "react";

/** Returns a ref for the shell's bar; when the rail opens, focus moves to the rail's close button inside it. */
export function useRailFocus(open: boolean) {
  const bar = useRef<HTMLElement>(null);

  useEffect(() => {
    if (open) bar.current?.querySelector<HTMLElement>(".shell-close")?.focus();
  }, [open]);

  return bar;
}
