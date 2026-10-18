import { useEffect, useLayoutEffect, useRef, type CSSProperties } from "react";
import { Link, useLocation } from "react-router-dom";
import {
  CheckSquareIcon,
  FileTextIcon,
  GraphIcon,
  MagnifyingGlassIcon,
  MicrophoneIcon,
  SidebarSimpleIcon,
  SignpostIcon,
  UsersThreeIcon,
  WaveformIcon,
  XIcon,
  type Icon,
} from "@phosphor-icons/react";
import type { ActionItem, MeetingSummary } from "../../api/types";
import { isDemo } from "../../api/mode";
import { brand } from "../../lib/brand";
import { duration } from "../../lib/format";
import { requestStrip, useSpeakerColour, useStrip, type StripData } from "../meeting/stripCache";
import ProductMark from "./ProductMark";
import { SystemStatus } from "./SystemStatus";
import ThemeToggle from "./ThemeToggle";
import { openAsk, openPalette, type SideCounts } from "./sidebarData";

interface NavItem {
  to: string;
  label: string;
  icon: Icon;
  count?: keyof SideCounts;
  /** read after the count, so "8" is announced as "8 open" */
  unit?: string;
  match: (path: string) => boolean;
}

const NAV: NavItem[] = [
  { to: "/meetings", label: "Meetings", icon: WaveformIcon, count: "meetings", match: (p) => p === "/meetings" || p.startsWith("/m/") },
  { to: "/commitments", label: "Commitments", icon: CheckSquareIcon, count: "commitments", unit: "open", match: (p) => p.startsWith("/commitments") },
  { to: "/decisions", label: "Decisions", icon: SignpostIcon, count: "decisions", unit: "current", match: (p) => p.startsWith("/decisions") },
  { to: "/people", label: "People", icon: UsersThreeIcon, count: "people", match: (p) => p.startsWith("/people") },
  { to: "/graph", label: "Graph", icon: GraphIcon, match: (p) => p.startsWith("/graph") },
  { to: "/documents", label: "Documents", icon: FileTextIcon, match: (p) => p.startsWith("/documents") },
];

const RECENT = 5;
const DUE = 3;
const isMac = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform);
const dayFmt = new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short" });

/** Talk time per speaker as conic stops, so each meeting's disc is pressed in the colours of who spoke and for how long. */
function discStops(d: StripData): string | null {
  const talk = new Map<string, number>();
  for (const s of d.segments) talk.set(s.track, (talk.get(s.track) ?? 0) + Math.max(0, s.t1 - s.t0));
  const total = [...talk.values()].reduce((a, b) => a + b, 0);
  if (!total) return null;
  const stops: string[] = [];
  let at = 0;
  for (const sp of d.speakers) {
    const t = talk.get(sp.track);
    if (!t) continue;
    const from = (at / total) * 360;
    at += t;
    stops.push(`var(--spk-${sp.colour}) ${from.toFixed(1)}deg ${((at / total) * 360).toFixed(1)}deg`);
  }
  return `conic-gradient(from -90deg, ${stops.join(", ")})`;
}

function MeetingDisc({ id }: { id: string }) {
  const entry = useStrip(id);
  useEffect(() => {
    if (entry.status === "idle") requestStrip(id);
  }, [entry.status, id]);
  const stops = entry.data ? discStops(entry.data) : null;
  const style = stops ? ({ "--grooves": stops } as CSSProperties) : undefined;
  return <span className={`side-disc${stops ? "" : " is-blank"}`} style={style} aria-hidden="true" />;
}

function RecentMeeting({ m, active, onNavigate }: { m: MeetingSummary; active: boolean; onNavigate: () => void }) {
  const live = m.status === "live";
  const title = m.title || "Untitled meeting";
  const day = Number(m.started_at) ? dayFmt.format(new Date(Number(m.started_at))) : "";
  const length = Number(m.duration_s) > 0 ? duration(Number(m.duration_s)) : "";
  return (
    <li data-tip={title}>
      <Link
        to={`/m/${encodeURIComponent(m.id)}`}
        className={`side-meet${active ? " is-active" : ""}${live ? " is-live" : ""}`}
        aria-current={active ? "page" : undefined}
        onClick={onNavigate}
      >
        <MeetingDisc id={m.id} />
        <span className="side-meet-text">
          <span className="side-meet-title">{title}</span>
          <span className="side-meet-meta">
            {live ? (
              <>
                <span className="live-dot" aria-hidden="true" />
                Live now
              </>
            ) : (
              [day, length].filter(Boolean).join(" · ")
            )}
          </span>
        </span>
      </Link>
    </li>
  );
}

function OpenItem({ it, onNavigate }: { it: ActionItem; onNavigate: () => void }) {
  const to = it.owner ? `/commitments?owner=${encodeURIComponent(it.owner)}` : "/commitments";
  const colour = useSpeakerColour(it.meeting_id, it.owner_track);
  const style = { "--spk": `var(--spk-${colour})` } as CSSProperties;
  return (
    <li>
      <Link to={to} className="side-due-item" style={style} onClick={onNavigate}>
        <span className="side-due-text">{it.text}</span>
        <span className="side-due-meta">
          <span className="side-due-owner">{it.owner ?? "Unassigned"}</span>
          {it.due && <span>Due {it.due}</span>}
        </span>
      </Link>
    </li>
  );
}

interface Props {
  id: string;
  rail: boolean;
  /** the rail can't be widened here (narrow screens force it), so the toggle hides */
  canToggle: boolean;
  onToggle: () => void;
  /** set inside the phone drawer: shows a close key and hides the status chip (the top bar has it) */
  onClose?: () => void;
  onNavigate: () => void;
  meetings: MeetingSummary[] | null;
  openItems: ActionItem[];
  counts: SideCounts;
}

export default function Sidebar({ id, rail, canToggle, onToggle, onClose, onNavigate, meetings, openItems, counts }: Props) {
  const { pathname } = useLocation();
  const navRef = useRef<HTMLElement>(null);
  const pillRef = useRef<HTMLSpanElement>(null);
  const anyLive = !!meetings?.some((m) => m.status === "live");
  const recent = meetings?.slice(0, RECENT) ?? null;

  // The white key behind the current section slides to it; placed by hand so it can travel between rows.
  useLayoutEffect(() => {
    const nav = navRef.current;
    const pill = pillRef.current;
    if (!nav || !pill) return;
    const place = () => {
      const a = nav.querySelector<HTMLElement>(".side-link.is-active");
      if (!a) {
        pill.style.opacity = "0";
        return;
      }
      // measured against the nav box itself: the folded rail positions each row for its name tag, which moves offsetTop
      const top = a.getBoundingClientRect().top - nav.getBoundingClientRect().top;
      pill.style.opacity = "1";
      pill.style.transform = `translateY(${top}px)`;
      pill.style.height = `${a.offsetHeight}px`;
      // the first placement lands without travelling; later ones glide
      requestAnimationFrame(() => pill.classList.add("is-placed"));
    };
    place();
    const ro = new ResizeObserver(place);
    ro.observe(nav);
    return () => ro.disconnect();
  }, [pathname]);

  const close = onClose ?? onNavigate;
  const ask = () => {
    close();
    openAsk();
  };
  const search = () => {
    close();
    openPalette();
  };

  return (
    <aside id={id} className={`side${rail ? " is-rail" : ""}`} aria-label="Sidebar">
      <div className="side-head">
        <Link to="/" className="side-brand" aria-label={`${brand.name} home`} onClick={onNavigate}>
          <ProductMark size={28} />
          <span className="side-brand-name side-fade">{brand.short}</span>
        </Link>
        {isDemo() && (
          <span className="side-demo side-fade" title="You're looking at bundled demo data. Start the API to use your own meetings.">
            Demo
          </span>
        )}
        {onClose && (
          <button type="button" className="side-icon side-close" onClick={onClose} aria-label="Close menu">
            <XIcon aria-hidden="true" />
          </button>
        )}
      </div>

      <div data-tip="Search" className="side-search-wrap">
        <button type="button" className="side-search" onClick={search} aria-label="Search and commands" aria-keyshortcuts="Meta+K Control+K">
          <MagnifyingGlassIcon aria-hidden="true" />
          <span className="side-search-label side-fade">Search or ask</span>
          <kbd className="side-fade">{isMac ? "⌘K" : "Ctrl K"}</kbd>
        </button>
      </div>

      <div className="side-scroll">
        <nav aria-label="Main" className="side-navbox" ref={navRef}>
          <span className="side-pill" ref={pillRef} aria-hidden="true" />
          <ul className="side-nav">
            {NAV.map(({ to, label, icon: NavIcon, count, unit, match }) => {
              const active = match(pathname);
              const n = count ? counts[count] : undefined;
              const live = to === "/meetings" && anyLive;
              return (
                <li key={to} data-tip={label}>
                  <Link to={to} className={`side-link${active ? " is-active" : ""}`} aria-current={active ? "page" : undefined} onClick={onNavigate}>
                    <NavIcon aria-hidden="true" weight={active ? "fill" : "regular"} />
                    <span className="side-label side-fade">{label}</span>
                    {live ? (
                      <span className="side-count is-live side-fade">
                        <span className="live-dot" aria-hidden="true" />
                        Live
                      </span>
                    ) : (
                      n !== undefined && (
                        <span className={`side-count side-fade${count === "commitments" && n > 0 ? " is-due" : ""}`}>
                          {n}
                          {unit && <span className="visually-hidden"> {unit}</span>}
                        </span>
                      )
                    )}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>

        <section className="side-recent" aria-labelledby={`${id}-recent`}>
          <h2 id={`${id}-recent`} className="side-heading">
            <span className="side-fade">Recent meetings</span>
          </h2>
          {recent === null ? (
            <ul className="side-meets" aria-hidden="true">
              {[0, 1].map((i) => (
                <li key={i} className="side-meet is-skeleton">
                  <span className="side-disc is-blank" />
                  <span className="side-meet-text side-fade">
                    <span className="skel" style={{ width: "78%" }} />
                    <span className="skel" style={{ width: "46%", height: 9 }} />
                  </span>
                </li>
              ))}
            </ul>
          ) : recent.length === 0 ? (
            <p className="side-empty side-fade">No meetings yet. Start one from Meetings.</p>
          ) : (
            <ul className="side-meets">
              {recent.map((m) => (
                <RecentMeeting key={m.id} m={m} active={pathname === `/m/${encodeURIComponent(m.id)}`} onNavigate={onNavigate} />
              ))}
            </ul>
          )}
        </section>

        {openItems.length > 0 && (
          <section className="side-recent side-due" aria-labelledby={`${id}-due`}>
            <h2 id={`${id}-due`} className="side-heading">
              Open commitments
            </h2>
            <ul className="side-dues">
              {openItems.slice(0, DUE).map((it) => (
                <OpenItem key={it.id} it={it} onNavigate={onNavigate} />
              ))}
            </ul>
          </section>
        )}
      </div>

      <div className="side-foot">
        <div data-tip="Ask out loud" className="side-ask-wrap">
          <button type="button" className="side-ask" onClick={ask} aria-keyshortcuts="/">
            <span className="side-ask-mic">
              <MicrophoneIcon aria-hidden="true" weight="fill" />
            </span>
            <span className="side-ask-text side-fade">
              <span className="side-ask-title">Ask out loud</span>
              <span className="side-ask-hint">Answers cite who said it</span>
            </span>
            <kbd className="side-fade" aria-hidden="true">
              /
            </kbd>
          </button>
        </div>

        <div className="side-tools">
          {!onClose && <SystemStatus />}
          <div data-tip="Theme">
            <ThemeToggle className="side-icon" />
          </div>
          {canToggle && (
            <div data-tip={rail ? "Expand  [" : "Collapse  ["} className="side-toggle-wrap">
              <button
                type="button"
                className="side-icon side-toggle"
                onClick={onToggle}
                aria-label={rail ? "Expand sidebar" : "Collapse sidebar"}
                aria-controls={id}
                aria-expanded={!rail}
                aria-keyshortcuts="["
              >
                <SidebarSimpleIcon aria-hidden="true" />
              </button>
            </div>
          )}
        </div>
      </div>
    </aside>
  );
}
