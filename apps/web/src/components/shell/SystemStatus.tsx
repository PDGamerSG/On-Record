import { useEffect, useId, useRef, useState } from "react";
import { api } from "../../api/client";
import { hub, useBusEvents } from "../../api/events";
import { isDemo } from "../../api/mode";
import type { Health } from "../../api/types";

const POLL_MS = 30_000;

type Tone = "ok" | "warn" | "pending";

interface StatusItem {
  key: string;
  tone: Tone;
  text: string;
  title?: string;
}

interface SystemState {
  health: Health | null;
  error: string | null;
  live: boolean;
  /** The event stream has connected at least once (first connect reads "connecting", later drops "reconnecting"). */
  wasLive: boolean;
}

function useSystemState(): SystemState {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [live, setLive] = useState(hub.connected);
  const [wasLive, setWasLive] = useState(hub.connected);

  // Keeps the shared event stream open app-wide, so "live updates" reflects reality on every page.
  useBusEvents(() => undefined);

  useEffect(() => {
    let alive = true;
    const check = () =>
      api
        .health()
        .then((h) => {
          if (!alive) return;
          setHealth(h);
          setError(null);
        })
        .catch((e: unknown) => {
          if (!alive) return;
          setError(e instanceof Error ? e.message : String(e));
        });
    check();
    const timer = window.setInterval(check, POLL_MS);
    let up = hub.connected;
    const off = hub.onStatus((c) => {
      setLive(c);
      if (c) setWasLive(true);
      if (c && !up) check(); // the API may have restarted while the stream was down
      up = c;
    });
    return () => {
      alive = false;
      window.clearInterval(timer);
      off();
    };
  }, []);

  return { health, error, live, wasLive };
}

const PROVIDERS: Record<string, string> = {
  ollama: "Ollama",
  gemini: "Gemini API",
  openai: "an OpenAI-compatible server",
  fake: "the offline test backend",
};

function questionText(v: string | undefined): string {
  if (!v) return "Voice questions unavailable";
  if (v.startsWith("gemma4-audio")) return "Questions heard by Gemma 4 audio";
  if (v === "whisper") return "Questions transcribed by Whisper";
  return `Questions heard by ${v}`;
}

function statusItems({ health, error, live, wasLive }: SystemState): StatusItem[] {
  const items: StatusItem[] = [];
  if (!health) {
    items.push(
      error
        ? { key: "api", tone: "warn", text: "API not reachable", title: `${error} Start the API on port 8000.` }
        : { key: "api", tone: "pending", text: "Checking the API" },
    );
  } else {
    const db = health.falkordb;
    items.push(
      db?.ok
        ? { key: "db", tone: "ok", text: `FalkorDB ${db.version ?? ""}`.trim(), title: db.graph ? `Graph ${db.graph}` : undefined }
        : { key: "db", tone: "warn", text: "FalkorDB not connected", title: "Start FalkorDB on port 6379, then reload." },
    );
    const llm = health.llm;
    if (llm?.model) {
      const where = PROVIDERS[llm.provider] ?? llm.provider;
      items.push({ key: "llm", tone: llm.provider === "fake" ? "warn" : "ok", text: `Answers by ${llm.model} on ${where}` });
    }
    items.push({ key: "ears", tone: health.question_audio ? "ok" : "warn", text: questionText(health.question_audio) });
    if (error) items.push({ key: "api", tone: "warn", text: "API stopped responding", title: error });
  }
  items.push(
    live
      ? { key: "sse", tone: "ok", text: "Live updates on" }
      : wasLive
        ? { key: "sse", tone: "warn", text: "Live updates reconnecting" }
        : { key: "sse", tone: "pending", text: "Live updates connecting" },
  );
  return items;
}

function summary(items: StatusItem[]): { tone: Tone; label: string; short: string } {
  if (isDemo()) return { tone: "ok", label: "Demo data. Show system details", short: "Demo data" };
  const problems = items.filter((i) => i.tone === "warn");
  if (problems.length) return { tone: "warn", label: `System status: ${problems.map((p) => p.text).join(", ")}`, short: problems.length === 1 ? problems[0].text : `${problems.length} issues` };
  if (items.some((i) => i.tone === "pending")) return { tone: "pending", label: "System status: checking", short: "Connecting" };
  return { tone: "ok", label: "System status: everything connected", short: "All systems live" };
}

/** In demo mode the bundled data stands in for the API, so say that plainly instead of listing services. */
const DEMO_ITEMS: StatusItem[] = [
  { key: "data", tone: "ok", text: "Two recorded meetings, bundled with the page" },
  { key: "ask", tone: "ok", text: "Answers replay what Gemma 4 said on this data" },
  { key: "api", tone: "pending", text: "Live capture and voice questions need the API" },
];

function Items({ items }: { items: StatusItem[] }) {
  return (
    <ul className="status-items">
      {items.map((i) => (
        <li key={i.key} className={`status-item is-${i.tone}`} title={i.title}>
          <span className="status-dot" aria-hidden="true" />
          {i.text}
          {i.tone === "warn" && <span className="visually-hidden"> (problem)</span>}
        </li>
      ))}
    </ul>
  );
}

/** One quiet chip in the top bar: a dot and a word, opening the full list of what's connected. */
export function SystemStatus() {
  const state = useSystemState();
  const items = isDemo() ? DEMO_ITEMS : statusItems(state);
  const { tone, label, short } = summary(items);
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const wrap = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      if (!wrap.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div className="status-pop-wrap" ref={wrap}>
      <button
        type="button"
        className={`status-toggle is-${tone}`}
        aria-label={label}
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((o) => !o)}
      >
        <span className="status-dot" aria-hidden="true" />
        <span className="status-toggle-label">{short}</span>
      </button>
      <div id={panelId} className="status-pop" hidden={!open}>
        <p className="status-pop-title">{isDemo() ? "You're viewing demo data" : "System"}</p>
        <Items items={items} />
      </div>
    </div>
  );
}
