import { useEffect, useRef, useState } from "react";
import { timecode } from "../../lib/format";
import type { Deck } from "../deck";
import { onThemeChange } from "../../lib/theme";
import { lineAt, speakerHex, speakingAt } from "../sides";
import { META } from "./meta";
import type { TurntableScene } from "./scene";

interface Hover {
  t: number;
  x: number;
  y: number;
}

function webglAvailable(): boolean {
  try {
    const c = document.createElement("canvas");
    return !!(c.getContext("webgl2") || c.getContext("webgl"));
  } catch {
    return false;
  }
}

/** The record on the platter. Click a groove to drop the needle there; hover to see who is in it. */
export default function Turntable({ deck }: { deck: Deck }) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const sceneRef = useRef<TurntableScene | null>(null);
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(() => !webglAvailable());
  const [hover, setHover] = useState<Hover | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const wrap = wrapRef.current;
    if (!canvas || !wrap || failed) return;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let scene: TurntableScene | null = null;
    let visible = true;
    let cancelled = false;
    const cleanups: (() => void)[] = [];

    void import("./scene").then(({ TurntableScene }) => {
      if (cancelled) return;
      scene = new TurntableScene(
        canvas,
        META,
        {
          time: () => deck.time(),
          playing: () => deck.state.playing,
          onHover: (h) => setHover(h),
          onPick: (t) => deck.seek(t),
          onReady: () => setReady(true),
        },
        reduced,
      );
      sceneRef.current = scene;
      const s = scene;
      if (import.meta.env.DEV) (window as unknown as { __deck?: TurntableScene }).__deck = s;
      const size = () => {
        const r = wrap.getBoundingClientRect();
        // wide screens: the deck sits right of centre, under the caption; narrow: centred in its own block
        const wide = window.matchMedia("(min-width: 1000px)").matches;
        s.framing.offsetX = wide ? 0.19 : 0;
        s.framing.offsetY = wide ? 0.06 : 0;
        // portrait screens see less width, so step back until the deck fits across
        const aspect = r.width / Math.max(1, r.height);
        s.framing.distance = wide ? 14.2 : 11.4 / Math.min(1, aspect / 1.45);
        s.setSize(Math.max(1, r.width), Math.max(1, r.height));
      };
      size();
      const ro = new ResizeObserver(size);
      ro.observe(wrap);
      cleanups.push(() => ro.disconnect());

      const io = new IntersectionObserver(([e]) => {
        visible = e.isIntersecting;
        if (reduced) return;
        if (visible && !document.hidden) s.start();
        else s.stop();
      });
      io.observe(wrap);
      cleanups.push(() => io.disconnect());
      const onVis = () => (document.hidden || !visible || reduced ? s.stop() : s.start());
      document.addEventListener("visibilitychange", onVis);
      cleanups.push(() => document.removeEventListener("visibilitychange", onVis));

      let sideShown = -1;
      const sync = () => {
        if (deck.state.side !== sideShown) {
          sideShown = deck.state.side;
          s.setSide(deck.current, speakerHex());
        }
        if (reduced) s.snap();
      };
      cleanups.push(deck.subscribe(sync));
      // the grooves are pressed in the speaker colours of the current theme
      cleanups.push(onThemeChange(() => s.setSide(deck.current, speakerHex())));
      // wait for the label's faces so the first pressing is typeset correctly
      void document.fonts.ready.then(() => {
        if (cancelled) return;
        sync();
        s.load("/landing/turntable.glb", "/landing/turntable-shadow.webp")
          .then(() => (reduced ? s.snap() : s.start()))
          .catch(() => setFailed(true));
      });
    });

    return () => {
      cancelled = true;
      cleanups.forEach((f) => f());
      scene?.dispose();
      sceneRef.current = null;
    };
  }, [deck, failed]);

  const side = deck.current;
  const hovered = hover ? (speakingAt(side, hover.t) ?? lineAt(side, hover.t)) : null;
  const colour = hovered ? (side.colours.get(hovered.speaker) ?? 7) : 7;

  return (
    <div
      ref={wrapRef}
      className={`deck${ready ? " is-ready" : ""}${failed ? " is-fallback" : ""}`}
      onPointerMove={(e) => sceneRef.current?.setPointer(e.clientX, e.clientY)}
      onPointerLeave={() => sceneRef.current?.setPointer(null)}
      onClick={(e) => sceneRef.current?.click(e.clientX, e.clientY)}
    >
      <canvas
        ref={canvasRef}
        className="deck-canvas"
        role="img"
        aria-label={`A turntable playing “${side.title}”. Each band of groove is coloured by whoever was speaking; the stylus is on the line quoted below.`}
      />
      {failed && <img className="deck-still" src="/landing/turntable-still.webp" alt="" width={1600} height={1067} />}
      {hover && hovered && (
        <div className={`deck-tip spk spk-${colour}`} style={{ left: hover.x, top: hover.y }} aria-hidden="true">
          <span className="deck-tip-who">
            <i className="deck-tip-dot" />
            {hovered.speaker_name ?? hovered.speaker}
            <span className="tc">{timecode(hover.t)}</span>
          </span>
          <span className="deck-tip-text">{hovered.text.length > 72 ? `${hovered.text.slice(0, 70).trimEnd()}…` : hovered.text}</span>
          <span className="deck-tip-hint">Click to drop the needle here</span>
        </div>
      )}
    </div>
  );
}
