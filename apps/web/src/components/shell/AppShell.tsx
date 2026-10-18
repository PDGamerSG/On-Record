import { useEffect, useState, type MouseEvent, type ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";
import {
  CheckSquareIcon,
  GraphIcon,
  MagnifyingGlassIcon,
  MicrophoneIcon,
  SignpostIcon,
  UsersThreeIcon,
  WaveformIcon,
  type Icon,
} from "@phosphor-icons/react";
import { brand } from "../../lib/brand";
import { isDemo } from "../../api/mode";
import ProductMark from "./ProductMark";
import { SystemStatus } from "./SystemStatus";
import ThemeToggle from "./ThemeToggle";
import "./AppShell.css";

interface NavItem {
  to: string;
  label: string;
  icon: Icon;
  match: (path: string) => boolean;
}

const NAV: NavItem[] = [
  { to: "/meetings", label: "Meetings", icon: WaveformIcon, match: (p) => p === "/meetings" || p.startsWith("/m/") },
  { to: "/commitments", label: "Commitments", icon: CheckSquareIcon, match: (p) => p.startsWith("/commitments") },
  { to: "/decisions", label: "Decisions", icon: SignpostIcon, match: (p) => p.startsWith("/decisions") },
  { to: "/people", label: "People", icon: UsersThreeIcon, match: (p) => p.startsWith("/people") },
  { to: "/graph", label: "Graph", icon: GraphIcon, match: (p) => p.startsWith("/graph") },
];

const isMac = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform);

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

export default function AppShell({ children }: { children: ReactNode }) {
  const { pathname } = useLocation();
  const scrolled = useScrolled();

  return (
    <div className="shell">
      <a href="#main" className="shell-skip" onClick={skipToMain}>
        Skip to main content
      </a>
      <header className={`shell-bar${scrolled ? " is-scrolled" : ""}`}>
        <div className="shell-bar-inner">
          <Link to="/" className="shell-brand" aria-label={`${brand.name} home`}>
            <ProductMark size={28} />
            <span className="shell-brand-name">{brand.short}</span>
          </Link>
          {isDemo() && (
            <span className="shell-demo" title="You're looking at bundled demo data. Start the API to use your own meetings.">
              Demo
            </span>
          )}

          <nav className="shell-nav" aria-label="Main">
            <ul>
              {NAV.map(({ to, label, icon: NavIcon, match }) => {
                const active = match(pathname);
                return (
                  <li key={to}>
                    <Link to={to} className={`shell-link${active ? " is-active" : ""}`} aria-current={active ? "page" : undefined}>
                      <NavIcon aria-hidden="true" weight={active ? "fill" : "regular"} />
                      <span className="shell-link-label">{label}</span>
                    </Link>
                  </li>
                );
              })}
            </ul>
          </nav>

          <div className="shell-tools">
            <button type="button" className="shell-search" onClick={openPalette} aria-label="Search and commands" aria-keyshortcuts="Meta+K Control+K">
              <MagnifyingGlassIcon aria-hidden="true" />
              <span className="shell-search-label">Search</span>
              <kbd>{isMac ? "⌘K" : "Ctrl K"}</kbd>
            </button>
            <SystemStatus />
            <ThemeToggle className="shell-icon" />
            <button type="button" className="shell-ask" onClick={openAsk} aria-keyshortcuts="/">
              <MicrophoneIcon aria-hidden="true" weight="fill" />
              <span>Ask</span>
              <kbd aria-hidden="true">/</kbd>
            </button>
          </div>
        </div>
      </header>

      <main id="main" className="shell-content" tabIndex={-1}>
        {children}
      </main>
    </div>
  );
}
