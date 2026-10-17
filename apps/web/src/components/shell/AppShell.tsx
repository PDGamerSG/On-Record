import { useEffect, useRef, useState, type MouseEvent, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { ListIcon, MicrophoneIcon } from "@phosphor-icons/react";
import { brand } from "../../lib/brand";
import { isDemo } from "../../api/mode";
import { isTypingTarget, useFocusTrap } from "../ask/useFocusTrap";
import ProductMark from "./ProductMark";
import Sidebar from "./Sidebar";
import { SystemStatus } from "./SystemStatus";
import { openAsk, useMedia, useRailChoice, useSidebarData } from "./sidebarData";
import "./AppShell.css";

const SIDEBAR_ID = "app-sidebar";

function skipToMain(e: MouseEvent<HTMLAnchorElement>) {
  const main = document.getElementById("main");
  if (!main) return;
  e.preventDefault();
  main.focus();
  main.scrollIntoView({ block: "start" });
}

/**
 * App frame: a sidebar on the left (sections, recent meetings, Ask) beside the page, which sits on its own inset panel.
 * Below 1100 px the sidebar folds to an icon rail; on phones it becomes a drawer behind a slim top bar.
 */
export default function AppShell({ children }: { children: ReactNode }) {
  const phone = useMedia("(max-width: 767px)");
  const narrow = useMedia("(max-width: 1099px)");
  const [railChoice, toggleRail] = useRailChoice();
  const [menuOpen, setMenuOpen] = useState(false);
  const drawerRef = useRef<HTMLDivElement>(null);
  const { meetings, openItems, counts } = useSidebarData();

  const drawerOpen = phone && menuOpen;
  const rail = !phone && (narrow || railChoice);
  const closeMenu = () => setMenuOpen(false);

  // "[" folds and unfolds the sidebar, as in most editors; text fields keep the key.
  useEffect(() => {
    if (phone || narrow) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "[" || e.ctrlKey || e.metaKey || e.altKey || e.defaultPrevented || isTypingTarget(e.target)) return;
      e.preventDefault();
      toggleRail();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [phone, narrow, toggleRail]);

  // The open drawer holds focus and the page stays put underneath it.
  useFocusTrap(drawerRef, drawerOpen);
  useEffect(() => {
    if (!drawerOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setMenuOpen(false);
    };
    const root = document.documentElement;
    const before = root.style.overflow;
    root.style.overflow = "hidden";
    window.addEventListener("keydown", onKey);
    return () => {
      root.style.overflow = before;
      window.removeEventListener("keydown", onKey);
    };
  }, [drawerOpen]);

  return (
    <div className={`shell${rail ? " is-rail" : ""}${drawerOpen ? " is-menu-open" : ""}`}>
      <a href="#main" className="shell-skip" onClick={skipToMain}>
        Skip to main content
      </a>

      {phone && (
        <header className="shell-top">
          <button
            type="button"
            className="side-icon shell-menu"
            onClick={() => setMenuOpen(true)}
            aria-label="Open menu"
            aria-expanded={menuOpen}
            aria-controls={SIDEBAR_ID}
          >
            <ListIcon aria-hidden="true" />
          </button>
          <Link to="/" className="side-brand" aria-label={`${brand.name} home`}>
            <ProductMark size={26} />
            <span className="side-brand-name">{brand.short}</span>
          </Link>
          {isDemo() && <span className="side-demo">Demo</span>}
          <div className="shell-top-tools">
            <SystemStatus />
            <button type="button" className="shell-ask" onClick={openAsk} aria-keyshortcuts="/">
              <MicrophoneIcon aria-hidden="true" weight="fill" />
              <span>Ask</span>
            </button>
          </div>
        </header>
      )}

      <div className="shell-side" ref={drawerRef} inert={phone && !menuOpen} role={drawerOpen ? "dialog" : undefined} aria-modal={drawerOpen || undefined} aria-label={drawerOpen ? "Menu" : undefined}>
        <Sidebar
          id={SIDEBAR_ID}
          rail={rail}
          canToggle={!phone && !narrow}
          onToggle={toggleRail}
          onClose={phone ? closeMenu : undefined}
          onNavigate={closeMenu}
          meetings={meetings}
          openItems={openItems}
          counts={counts}
        />
      </div>
      {phone && <div className="shell-scrim" onClick={closeMenu} aria-hidden="true" />}

      <main id="main" className="shell-content" tabIndex={-1}>
        {children}
      </main>
    </div>
  );
}
