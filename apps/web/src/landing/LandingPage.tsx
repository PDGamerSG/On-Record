// The landing page (/): the nav, the turntable hero and the sections described in docs/DESIGN.md.
// App.tsx loads it lazily, so three.js and the turntable only download on this page.
import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode, type RefObject } from "react";
import { Link } from "react-router-dom";
import { ArrowRightIcon } from "@phosphor-icons/react";
import ProductMark from "../components/shell/ProductMark";
import ThemeToggle from "../components/shell/ThemeToggle";
import { isDemo } from "../api/mode";
import { brand } from "../lib/brand";
import AskDemo from "./AskDemo";
import { Deck, useDeckState } from "./deck";
import Decisions from "./Decisions";
import LinerNotes from "./LinerNotes";
import LiveRoom from "./LiveRoom";
import NowPlaying from "./NowPlaying";
import Turntable from "./turntable/Turntable";
import Unspool from "./Unspool";
import "./landing.css";

const REPO = "https://github.com/PDGamerSG/On-Record";
const UPSTREAM = "https://github.com/Hydra-Of-Malice/hack-october-who-said-what-brain";
// The bundled demo has fixed meeting ids; a live API names its own, so send people to the list there.
const demoLink = () => (isDemo() ? "/m/demo-pricing-review" : "/meetings");

function GitHubMark() {
  return (
    <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true" focusable="false">
      <path
        fill="currentColor"
        d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"
      />
    </svg>
  );
}

const SECTIONS: [string, string, string[]][] = [
  ["how", "How it works", ["how", "listen"]],
  ["decisions", "Decisions", ["decisions"]],
  ["ask", "Ask", ["ask"]],
  ["notes", "Liner notes", ["notes"]],
];

function Nav({ deck }: { deck: Deck }) {
  const { playing } = useDeckState(deck);
  const [scrolled, setScrolled] = useState(false);
  const [hidden, setHidden] = useState(false);
  const [active, setActive] = useState<string | null>(null);
  const linksRef = useRef<HTMLElement>(null);
  const pillRef = useRef<HTMLSpanElement>(null);
  const progressRef = useRef<HTMLSpanElement>(null);

  // solid once scrolled; tucks away while you read down, returns the moment you scroll up
  useEffect(() => {
    let last = window.scrollY;
    const on = () => {
      const y = window.scrollY;
      setScrolled(y > 8);
      if (Math.abs(y - last) > 6) {
        setHidden(y > last && y > 640);
        last = y;
      }
      const run = document.documentElement.scrollHeight - window.innerHeight;
      if (progressRef.current) progressRef.current.style.transform = `scaleX(${run > 0 ? Math.min(1, y / run) : 0})`;
    };
    on();
    window.addEventListener("scroll", on, { passive: true });
    return () => window.removeEventListener("scroll", on);
  }, []);

  // which section is under the middle of the screen
  useEffect(() => {
    const owner = new Map(SECTIONS.flatMap(([id, , parts]) => parts.map((p) => [p, id] as const)));
    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries) if (e.isIntersecting) setActive(owner.get(e.target.id) ?? null);
      },
      { rootMargin: "-45% 0px -50% 0px" },
    );
    owner.forEach((_, id) => {
      const el = document.getElementById(id);
      if (el) io.observe(el);
    });
    // the hero and the closing belong to no section
    const ioTop = new IntersectionObserver((entries) => entries.some((e) => e.isIntersecting) && setActive(null), {
      rootMargin: "-45% 0px -50% 0px",
    });
    for (const id of ["top", "closing"]) {
      const el = document.getElementById(id);
      if (el) ioTop.observe(el);
    }
    return () => {
      io.disconnect();
      ioTop.disconnect();
    };
  }, []);

  // slide the pill under the active link
  useLayoutEffect(() => {
    const pill = pillRef.current;
    const link = active ? linksRef.current?.querySelector<HTMLElement>(`[data-id="${active}"]`) : null;
    if (!pill) return;
    if (!link) {
      pill.style.opacity = "0";
      return;
    }
    pill.style.opacity = "1";
    pill.style.width = `${link.offsetWidth}px`;
    pill.style.transform = `translateX(${link.offsetLeft}px)`;
  }, [active]);

  return (
    <header className={`l-nav${scrolled ? " is-scrolled" : ""}${hidden ? " is-hidden" : ""}`}>
      <div className="l-nav-inner">
        <a href="#top" className="l-brand" aria-label={`${brand.name}, top of page`}>
          <span className={`l-brand-mark${playing ? " is-spinning" : ""}`}>
            <ProductMark size={26} />
          </span>
          <span>{brand.name}</span>
        </a>
        <nav className="l-links" aria-label="Sections" ref={linksRef}>
          <span className="l-links-pill" ref={pillRef} aria-hidden="true" />
          {SECTIONS.map(([id, label]) => (
            <a key={id} href={`#${id}`} data-id={id} aria-current={active === id ? "true" : undefined}>
              {label}
            </a>
          ))}
        </nav>
        <div className="l-nav-end">
          <ThemeToggle className="l-icon-link" />
          <a className="l-icon-link" href={REPO} target="_blank" rel="noreferrer" aria-label="Source on GitHub">
            <GitHubMark />
          </a>
          <Link className="l-btn l-btn--light l-btn--sm" to={demoLink()}>
            Open the demo
          </Link>
        </div>
        <span className="l-nav-progress" ref={progressRef} aria-hidden="true" />
      </div>
    </header>
  );
}

function Hero({ deck }: { deck: Deck }) {
  return (
    <section className="hero" id="top" aria-labelledby="hero-title">
      <Turntable deck={deck} />
      <div className="hero-copy">
        <h1 id="hero-title" className="hero-title">
          Every meeting, remembered by who said it.
        </h1>
        <p className="hero-sub">It transcribes live, knows every voice, and answers spoken questions with the exact moment it came from.</p>
        <div className="hero-ctas">
          <Link className="l-btn l-btn--light" to={demoLink()}>
            Open the demo
            <ArrowRightIcon aria-hidden="true" />
          </Link>
          <a className="l-btn l-btn--dark" href="#how">
            See how it works
          </a>
        </div>
      </div>
      <NowPlaying deck={deck} />
    </section>
  );
}

function Stack() {
  const items = ["Gemma 4", "EmbeddingGemma", "Neo4j", "faster-whisper", "TitaNet", "Silero VAD"];
  return (
    <div className="stack" aria-label="Built on">
      <span className="stack-label">Built on open models</span>
      <ul className="stack-list">
        {items.map((x, i) => (
          <li key={x} data-reveal style={{ ["--d" as string]: i }}>
            {x}
          </li>
        ))}
      </ul>
    </div>
  );
}

function Section({ id, title, lede, children }: { id: string; title: ReactNode; lede: ReactNode; children: ReactNode }) {
  return (
    <section className="l-section" id={id} aria-labelledby={`${id}-title`}>
      <div className="l-wrap">
        <div className="l-head">
          <h2 id={`${id}-title`} className="l-h2" data-reveal>
            {title}
          </h2>
          <p className="l-lede" data-reveal style={{ ["--d" as string]: 1 }}>
            {lede}
          </p>
        </div>
        {children}
      </div>
    </section>
  );
}

const STAGES: [string, string, string][] = [
  ["Finds the speech", "Silero VAD", "Drops silence and noise."],
  ["Tells voices apart", "TitaNet", "Clusters voices into speakers, live."],
  ["Writes it down", "faster-whisper", "Words and timings for every turn."],
  ["Remembers it", "Neo4j", "Every line, linked in a graph."],
];

function Closing() {
  return (
    <section className="closing" id="closing" aria-labelledby="closing-title">
      <div className="closing-disc" aria-hidden="true">
        <img className="closing-record" src="/landing/record.webp" alt="" loading="lazy" width={1600} height={1600} />
        <span className="closing-sheen" />
      </div>
      <div className="closing-copy">
        <h2 id="closing-title" className="closing-title" data-reveal>
          Put your next meeting on record.
        </h2>
        <div className="hero-ctas closing-ctas" data-reveal style={{ ["--d" as string]: 2 }}>
          <Link className="l-btn l-btn--light" to={demoLink()}>
            Open the demo
            <ArrowRightIcon aria-hidden="true" />
          </Link>
          <a className="l-btn l-btn--dark" href={REPO} target="_blank" rel="noreferrer">
            <GitHubMark />
            Read the code
          </a>
        </div>
      </div>
    </section>
  );
}

function Footer() {
  return (
    <footer className="l-foot">
      <div className="l-wrap l-foot-grid">
        <div className="l-foot-brand">
          <ProductMark size={28} />
          <p>{brand.tagline}</p>
        </div>
        <nav aria-label="Product">
          <h3>Product</h3>
          <Link to="/meetings">Meetings</Link>
          <Link to="/commitments">Commitments</Link>
          <Link to="/decisions">Decisions</Link>
          <Link to="/graph">Graph</Link>
        </nav>
        <nav aria-label="Project">
          <h3>Project</h3>
          <a href={REPO} target="_blank" rel="noreferrer">
            Source on GitHub
          </a>
          <a href={UPSTREAM} target="_blank" rel="noreferrer">
            Who Said What Brain
          </a>
          <a href={`${REPO}/blob/main/LICENSE`} target="_blank" rel="noreferrer">
            Apache 2.0 licence
          </a>
        </nav>
        <div>
          <h3>Built for</h3>
          <p>{brand.event}</p>
          <p>{brand.track}</p>
          <p>{brand.problem_statement}</p>
        </div>
      </div>
      <p className="l-foot-word" aria-hidden="true">
        {brand.name}
      </p>
    </footer>
  );
}

/** Arms the scroll reveals once JS runs (content is visible without it), then marks each block as it enters. */
function useReveal(root: RefObject<HTMLDivElement | null>) {
  useEffect(() => {
    const el = root.current;
    if (!el || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    el.classList.add("reveal-armed");
    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (!e.isIntersecting) continue;
          e.target.classList.add("is-in");
          io.unobserve(e.target);
        }
      },
      { rootMargin: "0px 0px -10% 0px", threshold: 0.06 },
    );
    el.querySelectorAll("[data-reveal]").forEach((n) => io.observe(n));
    return () => io.disconnect();
  }, [root]);
}

export default function LandingPage() {
  const deck = useMemo(() => new Deck(), []);
  const rootRef = useRef<HTMLDivElement>(null);
  useReveal(rootRef);
  useEffect(() => {
    const title = document.title;
    document.title = `${brand.name}: ${brand.tagline}`;
    return () => {
      document.title = title;
      deck.dispose();
    };
  }, [deck]);

  return (
    <div className="landing" ref={rootRef}>
      <a className="l-skip" href="#how">
        Skip to how it works
      </a>
      <Nav deck={deck} />
      <main>
        <Hero deck={deck} />
        <Stack />
        <Unspool deck={deck} />
        <Section
          id="listen"
          title="It listens while you talk."
          lede="Each line lands in the graph about two seconds after the speaker pauses. Below, the real app replays the meeting as if it were live."
        >
          <ol className="stages">
            {STAGES.map(([what, who, how], i) => (
              <li key={what} className="stage" data-reveal style={{ ["--i" as string]: i, ["--d" as string]: i }}>
                <span className="stage-what">{what}</span>
                <span className="stage-who">{who}</span>
                <span className="stage-how">{how}</span>
              </li>
            ))}
          </ol>
          <LiveRoom deck={deck} />
        </Section>
        <div id="decisions">
          <Decisions deck={deck} />
        </div>
        <AskDemo deck={deck} />
        <LinerNotes />
        <Closing />
      </main>
      <Footer />
    </div>
  );
}
