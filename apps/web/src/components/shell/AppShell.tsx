// The frame around every app page (all but the landing): the top bar and navigation dock, which opens into
// a drawer that Escape or the backdrop closes, and the page itself.
import { useEffect, useState, type FocusEvent, type MouseEvent, type PointerEvent, type ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";
import {
  CheckSquareIcon,
  GraphIcon,
  MagnifyingGlassIcon,
  MicrophoneIcon,
  SignpostIcon,
  UsersThreeIcon,
  WaveformIcon,
  XIcon,
  type Icon,
} from "@phosphor-icons/react";
import { api } from "../../api/client";
import type { ActionItem, Decision, MeetingSummary, Person } from "../../api/types";
import { brand } from "../../lib/brand";
import { duration, speakerIndex } from "../../lib/format";
import ProductMark from "./ProductMark";
import { SystemStatus } from "./SystemStatus";
import ThemeToggle from "./ThemeToggle";
import "./AppShell.css";

type RailCountKey = "meetings" | "commitments" | "decisions" | "people";

interface NavItem {
  to: string;
  label: string;
  icon: Icon;
  match: (path: string) => boolean;
  countKey?: RailCountKey;
}

const NAV: NavItem[] = [
  { to: "/meetings", label: "Meetings", icon: WaveformIcon, match: (p) => p === "/meetings" || p.startsWith("/m/"), countKey: "meetings" },
  { to: "/commitments", label: "Commitments", icon: CheckSquareIcon, match: (p) => p.startsWith("/commitments"), countKey: "commitments" },
  { to: "/decisions", label: "Decisions", icon: SignpostIcon, match: (p) => p.startsWith("/decisions"), countKey: "decisions" },
  { to: "/people", label: "People", icon: UsersThreeIcon, match: (p) => p.startsWith("/people"), countKey: "people" },
  { to: "/graph", label: "Graph", icon: GraphIcon, match: (p) => p.startsWith("/graph") },
];

const isMac = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform);
const dockQuery = typeof window !== "undefined" ? window.matchMedia("(min-width: 768px)") : null;
const recentDate = new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short" });

interface RailData {
  meetings: MeetingSummary[];
  commitments: ActionItem[];
  decisions: Decision[];
  people: Person[];
  loaded: boolean;
}

const EMPTY_RAIL: RailData = { meetings: [], commitments: [], decisions: [], people: [], loaded: false };

function openAsk() {
  window.dispatchEvent(new CustomEvent("wsw:ask-open"));
}

function openPalette() {
  window.dispatchEvent(new CustomEvent("wsw:palette-open"));
}

function skipToMain(e: MouseEvent<HTMLAnchorElement>) {
  const main = document.getElementById("main");
  if (!main) return;
  e.preventDefault();
  main.focus();
  main.scrollIntoView({ block: "start" });
}

/** A hairline appears under the bar once the page scrolls beneath it. */
function useScrolled(): boolean {
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const on = () => setScrolled(window.scrollY > 4);
    on();
    window.addEventListener("scroll", on, { passive: true });
    return () => window.removeEventListener("scroll", on);
  }, []);
  return scrolled;
}

interface DockTip {
  label: string;
  top: number;
}

/**
 * Names a dock key beside the dock while it is hovered or keyboard-focused. The dock hides its labels, and the bar
 * both scrolls and blurs what is behind it, which clips anything positioned inside it, so the tip is drawn outside
 * the bar. Keys opt in with `data-label`.
 */
function useDockTip(railOpen: boolean) {
  const [tip, setTip] = useState<DockTip | null>(null);

  const show = (target: EventTarget) => {
    const key = target instanceof Element ? target.closest<HTMLElement>("[data-label]") : null;
    if (!key || !dockQuery?.matches) {
      setTip(null);
      return;
    }
    const box = key.getBoundingClientRect();
    setTip({ label: key.dataset.label ?? "", top: box.top + box.height / 2 });
  };
  const hide = () => setTip(null);

  return {
    tip: railOpen ? null : tip,
    hide,
    handlers: {
      onPointerOver: (e: PointerEvent<HTMLElement>) => {
        if (e.pointerType === "mouse") show(e.target);
      },
      onPointerLeave: hide,
      onFocus: (e: FocusEvent<HTMLElement>) => {
        if (e.target.matches(":focus-visible")) show(e.target);
      },
      onBlur: hide,
    },
  };
}

function useRailData(): RailData {
  const [data, setData] = useState<RailData>(EMPTY_RAIL);

  useEffect(() => {
    let alive = true;
    Promise.allSettled([api.meetings(), api.actionItems({ status: "open" }), api.decisions(), api.people()]).then(([meetings, commitments, decisions, people]) => {
      if (!alive) return;
      setData({
        meetings: meetings.status === "fulfilled" ? meetings.value : [],
        commitments: commitments.status === "fulfilled" ? commitments.value : [],
        decisions: decisions.status === "fulfilled" ? decisions.value : [],
        people: people.status === "fulfilled" ? people.value : [],
        loaded: true,
      });
    });
    return () => {
      alive = false;
    };
  }, []);

  return data;
}

function meetingMeta(meeting: MeetingSummary): string {
  return `${recentDate.format(new Date(meeting.started_at))} · ${duration(meeting.duration_s)}`;
}

export default function AppShell({ children }: { children: ReactNode }) {
  const { pathname } = useLocation();
  const scrolled = useScrolled();
  const railData = useRailData();
  const [railOpen, setRailOpen] = useState(false);
  const dockTip = useDockTip(railOpen);

  useEffect(() => {
    if (!railOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setRailOpen(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [railOpen]);

  const counts: Record<RailCountKey, number> = {
    meetings: railData.meetings.length,
    commitments: railData.commitments.length,
    decisions: railData.decisions.length,
    people: railData.people.length,
  };

  const handleSearch = () => {
    if (!railOpen) {
      setRailOpen(true);
      return;
    }
    openPalette();
  };

  return (
    <div className={`shell${railOpen ? " is-rail-open" : ""}`}>
      <a href="#main" className="shell-skip" onClick={skipToMain}>
        Skip to main content
      </a>
      {railOpen && <button type="button" className="shell-backdrop" aria-label="Close navigation" onClick={() => setRailOpen(false)} />}
      <header className={`shell-bar${scrolled ? " is-scrolled" : ""}`} {...dockTip.handlers}>
        <div className="shell-bar-inner" onScroll={dockTip.hide}>
          <div className="shell-brand-row">
            <button type="button" className="shell-dock-brand" onClick={() => setRailOpen(true)} aria-label="Open navigation">
              <ProductMark size={30} />
            </button>
            <Link to="/" className="shell-brand" aria-label={`${brand.name} home`}>
              <ProductMark size={38} />
              <span className="shell-brand-name">{brand.short}</span>
            </Link>
            <button type="button" className="shell-close" onClick={() => setRailOpen(false)} aria-label="Close navigation">
              <XIcon aria-hidden="true" />
            </button>
          </div>

          <button type="button" className="shell-search" onClick={handleSearch} aria-label={railOpen ? "Search and commands" : "Open navigation"} aria-keyshortcuts="Meta+K Control+K">
            <MagnifyingGlassIcon aria-hidden="true" />
            <span className="shell-search-label">Search or ask</span>
            <kbd>{isMac ? "⌘K" : "Ctrl K"}</kbd>
          </button>

          <nav className="shell-nav" aria-label="Main">
            <ul>
              {NAV.map(({ to, label, icon: NavIcon, match, countKey }) => {
                const active = match(pathname);
                return (
                  <li key={to}>
                    <Link
                      to={to}
                      className={`shell-link${active ? " is-active" : ""}`}
                      aria-current={active ? "page" : undefined}
                      data-label={label}
                      onClick={() => setRailOpen(false)}
                    >
                      <NavIcon aria-hidden="true" weight={active ? "fill" : "regular"} />
                      <span className="shell-link-label">{label}</span>
                      {railData.loaded && countKey ? (
                        <span className="shell-count">{counts[countKey]}</span>
                      ) : null}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </nav>

          <section className="shell-recent" aria-labelledby="shell-recent-title">
            <h2 id="shell-recent-title">Recent meetings</h2>
            <ul>
              {railData.meetings.slice(0, 2).map((meeting) => (
                <li key={meeting.id}>
                  <Link
                    to={`/m/${encodeURIComponent(meeting.id)}`}
                    aria-current={pathname === `/m/${encodeURIComponent(meeting.id)}` ? "page" : undefined}
                    data-label={meeting.title}
                    onClick={() => setRailOpen(false)}
                  >
                    <ProductMark size={34} />
                    <span className="shell-recent-copy">
                      <strong>{meeting.title}</strong>
                      <span>{meetingMeta(meeting)}</span>
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          </section>

          <section className="shell-commitments" aria-labelledby="shell-commitments-title">
            <h2 id="shell-commitments-title">Open commitments</h2>
            <ul>
              {railData.commitments.slice(0, 3).map((item) => (
                <li key={item.id} className={`spk spk-${speakerIndex(item.owner_track)}`}>
                  <Link to={`/commitments?owner=${encodeURIComponent(item.owner ?? "")}`} onClick={() => setRailOpen(false)}>
                    <span>{item.text}</span>
                    <small>
                      {item.owner ?? "Unassigned"}
                      {item.due ? ` · Due ${item.due}` : ""}
                    </small>
                  </Link>
                </li>
              ))}
            </ul>
          </section>

          <div className="shell-tools">
            <SystemStatus />
            <ThemeToggle className="shell-icon" />
            <button type="button" className="shell-ask" onClick={openAsk} aria-label="Ask out loud" aria-keyshortcuts="/" data-label="Ask out loud">
              <MicrophoneIcon aria-hidden="true" weight="fill" />
              <span className="shell-ask-label">Ask</span>
              <span className="shell-ask-expanded-label">Ask out loud</span>
              <kbd aria-hidden="true">/</kbd>
            </button>
          </div>
        </div>
      </header>
      {dockTip.tip && (
        <span key={dockTip.tip.label} className="shell-tip" style={{ top: dockTip.tip.top }} aria-hidden="true">
          {dockTip.tip.label}
        </span>
      )}

      <main id="main" className="shell-content" tabIndex={-1}>
        {children}
      </main>
    </div>
  );
}
