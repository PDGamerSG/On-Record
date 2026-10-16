import { useEffect, useRef, type KeyboardEvent, type MouseEvent } from "react";
import { LoaderCircle, Pause, Play, SkipBack, SkipForward, Volume2, VolumeX } from "lucide-react";
import { timecode } from "../lib/format";
import { useDeckState, useNowPlaying, type Deck } from "./deck";
import { SIDES, type Side } from "./sides";
import raw from "../api/demo/fixtures.json";

const ROLES = new Map((raw as unknown as { people: { name: string; role?: string }[] }).people.map((p) => [p.name, p.role ?? ""]));

/** Who spoke when across the whole side, with the playhead. Click or use the arrow keys to seek. */
export function Tape({ deck, side, label }: { deck: Deck; side: Side; label: string }) {
  const headRef = useRef<HTMLSpanElement>(null);
  const tapeRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let raf = 0;
    const tick = () => {
      const f = Math.min(1, deck.time() / side.duration);
      if (headRef.current) headRef.current.style.transform = `translateX(${(f * 100).toFixed(3)}cqw)`;
      tapeRef.current?.setAttribute("aria-valuenow", String(Math.floor(deck.time())));
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [deck, side]);

  const onClick = (e: MouseEvent<HTMLDivElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    deck.seek(((e.clientX - r.left) / r.width) * side.duration);
  };
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const step = e.shiftKey ? 30 : 5;
    if (e.key === "ArrowRight") deck.seek(deck.time() + step);
    else if (e.key === "ArrowLeft") deck.seek(deck.time() - step);
    else if (e.key === "Home") deck.seek(0);
    else return;
    e.preventDefault();
  };

  return (
    <div
      ref={tapeRef}
      className="tape"
      role="slider"
      tabIndex={0}
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={Math.floor(side.duration)}
      aria-valuetext={timecode(deck.time())}
      onClick={onClick}
      onKeyDown={onKey}
    >
      {side.utterances.map((u) => (
        <i
          key={u.id}
          className={`tape-block spk spk-${side.colours.get(u.speaker) ?? 7}`}
          style={{ left: `${(u.t_start / side.duration) * 100}%`, width: `${((u.t_end - u.t_start) / side.duration) * 100}%` }}
        />
      ))}
      <span ref={headRef} className="tape-head" />
    </div>
  );
}

export default function NowPlaying({ deck }: { deck: Deck }) {
  const state = useDeckState(deck);
  const { line: playing, second } = useNowPlaying(deck);
  const side = deck.current;
  // before the first word, caption the first line rather than nothing
  const line = playing ?? side.utterances[0] ?? null;
  const colour = line ? (side.colours.get(line.speaker) ?? 7) : 7;
  const idx = line ? side.utterances.indexOf(line) : -1;
  const jump = (d: number) => {
    const next = side.utterances[Math.max(0, Math.min(side.utterances.length - 1, idx + d))];
    if (next) deck.seek(next.t_start + 0.05);
  };

  return (
    <section className="now" aria-label="Now playing">
      <figure className={`now-line spk spk-${colour}`} aria-live="polite">
        {line && (
          <div className="now-line-inner" key={line.id}>
            <figcaption className="now-who">
              <i className="now-dot" aria-hidden="true" />
              <span className="now-name">{line.speaker_name ?? line.speaker}</span>
              {ROLES.get(line.speaker_name ?? "") && <span className="now-role">{ROLES.get(line.speaker_name ?? "")}</span>}
              <span className="tc now-at">{timecode(line.t_start)}</span>
            </figcaption>
            <blockquote className="now-quote">{line.text}</blockquote>
          </div>
        )}
      </figure>

      <div className="now-bar">
        <div className="now-sides" role="group" aria-label="Side">
          {SIDES.map((s, i) => (
            <button key={s.id} type="button" className="now-side" aria-pressed={state.side === i} title={s.title} onClick={() => deck.setSide(i)}>
              {s.letter}
            </button>
          ))}
        </div>
        <div className="now-track">
          <div className="now-track-meta">
            <span className="now-track-title">{side.title}</span>
            <span className="tc">
              {timecode(second)} <span className="now-of">/ {timecode(side.duration)}</span>
            </span>
          </div>
          <Tape deck={deck} side={side} label={`Position in ${side.title}`} />
        </div>
        <div className="now-buttons">
          <button type="button" className="now-icon" onClick={() => jump(-1)} aria-label="Previous line">
            <SkipBack aria-hidden="true" />
          </button>
          <button type="button" className="now-icon now-icon--main" onClick={() => deck.togglePlaying()} aria-label={state.playing ? "Pause" : "Play"}>
            {state.playing ? <Pause aria-hidden="true" /> : <Play aria-hidden="true" />}
          </button>
          <button type="button" className="now-icon" onClick={() => jump(1)} aria-label="Next line">
            <SkipForward aria-hidden="true" />
          </button>
        </div>
        <button type="button" className={`now-sound${state.sound ? " is-on" : ""}`} aria-pressed={state.sound} onClick={() => void deck.setSound(!state.sound)}>
          {state.sound ? state.loading ? <LoaderCircle className="spin" aria-hidden="true" /> : <Volume2 aria-hidden="true" /> : <VolumeX aria-hidden="true" />}
          <span>{state.sound ? "Sound on" : "Listen"}</span>
        </button>
      </div>
      {state.error && <p className="now-error">{state.error}</p>}
    </section>
  );
}
