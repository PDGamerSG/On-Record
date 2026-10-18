// Every app page names the browser tab after itself, so a page never keeps the title the previous page set.
import { useEffect } from "react";
import { brand } from "./brand";

/**
 * Sets the tab title to "<page> - On Record", or to the product name alone when there is no page name. Pass null to
 * leave the title to a component further down (the meeting room names the tab once the meeting has loaded).
 */
export function usePageTitle(page?: string | null): void {
  useEffect(() => {
    if (page === null) return;
    document.title = page ? `${page} - ${brand.short}` : brand.name;
  }, [page]);
}
