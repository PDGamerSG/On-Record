// Every app page names the browser tab after itself, so a page never keeps the title the previous page set.
import { useEffect } from "react";
import { brand } from "./brand";

/** Sets the tab title to "<page> - On Record", or to the product name alone when there is no page name. */
export function usePageTitle(page?: string): void {
  useEffect(() => {
    document.title = page ? `${page} - ${brand.short}` : brand.name;
  }, [page]);
}
