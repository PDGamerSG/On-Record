// What the sidebar shows besides links: the newest meetings and a count beside each section, kept current from bus events.
import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { api } from "../../api/client";
import { useBusEvents } from "../../api/events";
import type { ActionItem, BusEvent, MeetingSummary } from "../../api/types";

export interface SideCounts {
  meetings?: number;
  commitments?: number;
  decisions?: number;
  people?: number;
}

const REFRESH_MS = 800;
const REFRESH_ON = new Set<BusEvent["type"]>(["meeting.started", "meeting.ended", "insight.created", "action.updated", "speaker.named", "speaker.merged"]);

export function openAsk() {
  window.dispatchEvent(new CustomEvent("wsw:ask-open"));
}

export function openPalette() {
  window.dispatchEvent(new CustomEvent("wsw:palette-open"));
}

const newestFirst = (a: MeetingSummary, b: MeetingSummary) => (Number(b.started_at) || 0) - (Number(a.started_at) || 0);

export interface SidebarData {
  meetings: MeetingSummary[] | null;
  /** open action items, newest first */
  openItems: ActionItem[];
  counts: SideCounts;
}

export function useSidebarData(): SidebarData {
  const [meetings, setMeetings] = useState<MeetingSummary[] | null>(null);
  const [openItems, setOpenItems] = useState<ActionItem[]>([]);
  const [counts, setCounts] = useState<SideCounts>({});
  const timer = useRef<number | null>(null);

  // Each call settles on its own, so one slow or failing endpoint never blanks the other counts.
  const load = useCallback(() => {
    const count = (key: keyof SideCounts, n: number | undefined) => setCounts((c) => ({ ...c, [key]: n }));
    api
      .meetings()
      .then((list) => {
        const ok = Array.isArray(list) ? list.filter((m) => m && typeof m.id === "string").sort(newestFirst) : [];
        setMeetings(ok);
        count("meetings", ok.length);
      })
      .catch(() => setMeetings((m) => m ?? []));
    api
      .actionItems({ status: "open" })
      .then((items) => {
        const ok = Array.isArray(items) ? items.filter((i) => i && typeof i.id === "string") : [];
        setOpenItems(ok.sort((a, b) => (Number(b.created_at) || 0) - (Number(a.created_at) || 0)));
        count("commitments", Array.isArray(items) ? ok.length : undefined);
      })
      .catch(() => undefined);
    api
      .decisions()
      .then((ds) => count("decisions", Array.isArray(ds) ? ds.filter((d) => d.status !== "superseded").length : undefined))
      .catch(() => undefined);
    api
      .people()
      .then((ps) => count("people", Array.isArray(ps) ? ps.length : undefined))
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    load();
    return () => {
      if (timer.current) window.clearTimeout(timer.current);
    };
  }, [load]);

  useBusEvents((e) => {
    if (!REFRESH_ON.has(e.type)) return;
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(load, REFRESH_MS);
  });

  return { meetings, openItems, counts };
}

/** Live result of a CSS media query. */
export function useMedia(query: string): boolean {
  const subscribe = useCallback(
    (fn: () => void) => {
      const mq = window.matchMedia(query);
      mq.addEventListener("change", fn);
      return () => mq.removeEventListener("change", fn);
    },
    [query],
  );
  return useSyncExternalStore(subscribe, () => window.matchMedia(query).matches, () => false);
}

const RAIL_KEY = "onrecord-sidebar";

/** The sidebar's collapsed (icon rail) choice, remembered across visits. */
export function useRailChoice(): [boolean, () => void] {
  const [rail, setRail] = useState(() => {
    try {
      return localStorage.getItem(RAIL_KEY) === "rail";
    } catch {
      return false;
    }
  });
  const toggle = useCallback(() => {
    setRail((r) => {
      try {
        localStorage.setItem(RAIL_KEY, r ? "full" : "rail");
      } catch {
        // private mode: the choice lasts for this page only
      }
      return !r;
    });
  }, []);
  return [rail, toggle];
}
