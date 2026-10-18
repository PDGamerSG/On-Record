// Keeps keyboard focus on screen as the desktop rail opens and closes. The dock's buttons are hidden once the rail is
// open and the rail's close button is hidden once it shuts, so without this the focused button disappears and focus
// falls to the page body.
import { useCallback, useEffect, useRef } from "react";

/**
 * Returns a ref for the shell's bar and close(), which shuts the rail and hands focus back to the dock's "Open
 * navigation" button. When the rail opens, focus moves to its close button. Closing by following a link inside the
 * rail should use the plain setter, so focus stays with the page the link opened.
 */
export function useRailFocus(open: boolean, setOpen: (open: boolean) => void) {
  const bar = useRef<HTMLElement>(null);
  const backToDock = useRef(false);

  useEffect(() => {
    const el = bar.current;
    if (!el) return;
    if (open) {
      el.querySelector<HTMLElement>(".shell-close")?.focus();
    } else if (backToDock.current) {
      backToDock.current = false;
      el.querySelector<HTMLElement>(".shell-dock-brand")?.focus();
    }
  }, [open]);

  const close = useCallback(() => {
    backToDock.current = true;
    setOpen(false);
  }, [setOpen]);

  return { bar, close };
}
