import { useEffect, useEffectEvent, useRef, useState } from "react";
import { CheckIcon, CircleNotchIcon, MicrophoneIcon, PlayIcon, ArrowCounterClockwiseIcon } from "@phosphor-icons/react";
import { demoApi } from "../api/demo/demoApi";
import type { AskResult, Hit } from "../api/types";
import { newSessionId, timecode } from "../lib/format";
import { answerBlocks, formatArgs, ms, timingLabel } from "../components/ask/askFormat";
import { playLine, type Deck } from "./deck";
import { SIDES } from "./sides";

const SCRIPT = ["What did Priya commit to?", "And when is that due?", "Mark it done."];
const LISTEN_MS = 1300;

type Stage = "idle" | "listening" | "thinking" | "answered";

interface Turn {
  q: string;
  result: AskResult | null;
}

function Citation({ deck, c }: { deck: Deck; c: Hit }) {
  const side = SIDES.find((s) => s.id === c.meeting_id);
  const u = side?.utterances.find((x) => x.id === c.utterance_id);
  if (!side || !u) return null;
  return (
    <li className={`cite spk spk-${side.colours.get(u.speaker) ?? 7}`}>
      <button type="button" className="cite-play" onClick={() => playLine(deck, side, u)} aria-label={`Play ${u.speaker_name} at ${timecode(u.t_start)}`}>
        <PlayIcon weight="fill" aria-hidden="true" />
      </button>
      <div className="cite-body">
        <span className="cite-meta">
          <b>{u.speaker_name}</b> {side.title} <span className="tc">{timecode(u.t_start)}</span>
        </span>
        <span className="cite-text">{u.text}</span>
      </div>
    </li>
  );
}

function Why({ r }: { r: AskResult }) {
  const timings = Object.entries(r.timings).filter(([, v]) => Number.isFinite(v));
  const total = timings.find(([k]) => k === "total_ms")?.[1] ?? Math.max(...timings.map(([, v]) => v));
  return (
    <div className="why">
      <div className="why-col">
        <h4 className="why-h">Tools Gemma called</h4>
        <ul className="why-tools">
          {r.tool_trace.map((t, i) => (
            <li key={i}>
              <code className="why-tool">{t.tool}</code>
              <span className="why-args">{formatArgs(t.args)}</span>
              <span className="tc why-n">
                {t.result_count} found · {ms(t.ms)}
              </span>
            </li>
          ))}
        </ul>
        <h4 className="why-h">Time</h4>
        <ul className="why-times">
          {timings.map(([k, v]) => (
            <li key={k}>
              <span>{timingLabel(k.replace(/_ms$/, ""))}</span>
              <i style={{ width: `${Math.max(3, (v / total) * 100)}%` }} />
              <span className="tc">{ms(v)}</span>
            </li>
          ))}
        </ul>
      </div>
      <div className="why-col">
        <h4 className="why-h">The Cypher that ran</h4>
        {r.cypher.map((c, i) => (
          <pre key={i} className="why-code">
            <code>{c}</code>
          </pre>
        ))}
      </div>
    </div>
  );
}

function Answer({ text, animate }: { text: string; animate: boolean }) {
  const [shown, setShown] = useState(animate ? 0 : text.length);
  useEffect(() => {
    if (!animate) return;
    let i = 0;
    const words = text.split(/(\s+)/);
    const id = window.setInterval(() => {
      i += 2;
      setShown(words.slice(0, i).join("").length);
      if (i >= words.length) window.clearInterval(id);
    }, 38);
    return () => window.clearInterval(id);
  }, [text, animate]);
  return (
    <div className="turn-answer">
      {answerBlocks(text.slice(0, shown)).map((b, i) =>
        b.kind === "p" ? (
          <p key={i}>{b.text}</p>
        ) : (
          <ul key={i}>
            {b.items.map((it, j) => (
              <li key={j}>{it}</li>
            ))}
          </ul>
        ),
      )}
    </div>
  );
}

export default function AskDemo({ deck }: { deck: Deck }) {
  const [session, setSession] = useState(newSessionId);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [stage, setStage] = useState<Stage>("idle");
  const sectionRef = useRef<HTMLElement>(null);
  const threadRef = useRef<HTMLOListElement>(null);
  const started = useRef(false);
  const [reduced] = useState(() => window.matchMedia("(prefers-reduced-motion: reduce)").matches);

  const next = turns.length < SCRIPT.length ? SCRIPT[turns.length] : null;
  const busy = stage === "listening" || stage === "thinking";

  const ask = async (q: string) => {
    if (busy) return;
    setStage("listening");
    if (!reduced) await new Promise((r) => window.setTimeout(r, LISTEN_MS));
    setTurns((t) => [...t, { q, result: null }]);
    setStage("thinking");
    const result = await demoApi.ask(session, q);
    setTurns((t) => t.map((x, i) => (i === t.length - 1 ? { ...x, result } : x)));
    setStage("answered");
  };

  const reset = () => {
    setSession(newSessionId());
    setTurns([]);
    setStage("idle");
  };

  // ask the first question once, when the section comes into view
  const askFirst = useEffectEvent(() => void ask(SCRIPT[0]));
  useEffect(() => {
    const el = sectionRef.current;
    if (!el) return;
    const io = new IntersectionObserver(
      ([e]) => {
        if (e.isIntersecting && !started.current) {
          started.current = true;
          askFirst();
        }
      },
      { threshold: 0.45 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);

  useEffect(() => {
    const el = threadRef.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: reduced ? "auto" : "smooth" });
  }, [turns, stage, reduced]);

  const last = turns[turns.length - 1]?.result ?? null;

  return (
    <section ref={sectionRef} className="l-section ask" id="ask" aria-labelledby="ask-title">
      <div className="l-wrap ask-grid">
        <div className="ask-copy">
          <h2 id="ask-title" className="l-h2" data-reveal>
            Ask it out loud.
          </h2>
          <p className="l-lede" data-reveal style={{ ["--d" as string]: 1 }}>
            Gemma 4 hears your question, searches the graph and answers with the moment it came from. Follow-ups work. So does “mark it done.”
          </p>

          <div className="talk" data-reveal style={{ ["--d" as string]: 2 }}>
            <img className={`talk-mic is-${stage}`} src="/landing/mic.webp" alt="" width={460} height={1220} loading="lazy" />
            <div className="talk-controls">
            <button
              type="button"
              className={`talk-btn is-${stage}`}
              onClick={() => (next ? void ask(next) : reset())}
              disabled={busy}
              aria-label={next ? `Ask: ${next}` : "Start the conversation again"}
            >
              <span className="talk-rings" aria-hidden="true">
                <i />
                <i />
                <i />
              </span>
              {stage === "thinking" ? <CircleNotchIcon className="spin" aria-hidden="true" /> : next ? <MicrophoneIcon aria-hidden="true" /> : <ArrowCounterClockwiseIcon aria-hidden="true" />}
            </button>
            <div className="talk-state" aria-live="polite">
              {stage === "listening" ? "Listening…" : stage === "thinking" ? "Searching the graph…" : next ? "Press to ask next" : "Start again"}
            </div>
            </div>
          </div>

          <ol className="script">
            {SCRIPT.map((q, i) => {
              const done = i < turns.length;
              return (
                <li key={q} className={`script-q${done ? " is-done" : ""}${i === turns.length ? " is-next" : ""}`}>
                  <span className="script-n tc" aria-hidden="true">
                    {done ? <CheckIcon /> : i + 1}
                  </span>
                  {q}
                </li>
              );
            })}
          </ol>
        </div>

        <div className="console" aria-label="Conversation" data-reveal="frame" style={{ ["--d" as string]: 2 }}>
          <div className="console-bar">
            <span className="console-title">Ask</span>
            <span className="console-model">{last ? `${last.model} · demo answers` : "gemma4:12b-it-qat"}</span>
          </div>
          <ol className="thread" ref={threadRef}>
            {turns.length === 0 && <li className="thread-empty">Press the mic to ask the first question.</li>}
            {turns.map((t, i) => (
              <li key={i} className="turn">
                <p className="turn-q">{t.q}</p>
                {t.result ? (
                  <>
                    <Answer text={t.result.answer} animate={!reduced && i === turns.length - 1} />
                    {t.result.citations.length > 0 && (
                      <ul className="cites">
                        {t.result.citations.slice(0, 2).map((c) => (
                          <Citation key={c.utterance_id} deck={deck} c={c} />
                        ))}
                      </ul>
                    )}
                  </>
                ) : (
                  <p className="turn-wait">
                    <CircleNotchIcon className="spin" aria-hidden="true" /> Searching the graph
                  </p>
                )}
              </li>
            ))}
          </ol>
          {last && (
            <details className="console-why">
              <summary>Why this answer</summary>
              <Why r={last} />
            </details>
          )}
        </div>
      </div>
    </section>
  );
}
