import { useEffect, useRef } from "react";
import { timecode } from "../lib/format";
import { useDeckState, type Deck } from "./deck";
import { speakerHex, type Side } from "./sides";

const TURNS = 6.5;
const smooth = (x: number) => x * x * (3 - 2 * x);
const clamp01 = (x: number) => Math.min(1, Math.max(0, x));

interface Layout {
  w: number;
  h: number;
  cx: number;
  cy: number;
  ro: number;
  ri: number;
  laneX0: number;
  laneX1: number;
  laneY: number[];
  laneH: number;
}

function layout(w: number, h: number, lanes: number, narrow: boolean): Layout {
  // narrow: the copy owns the top of the screen, so the record and its lanes share the bottom half
  const ro = narrow ? Math.min(w * 0.4, h * 0.19) : Math.min(h * 0.36, w * 0.21);
  const cx = narrow ? w / 2 : w * 0.7;
  const cy = narrow ? h * 0.71 : h * 0.5;
  const laneX0 = narrow ? 76 : Math.max(150, w * 0.12);
  const laneX1 = w - (narrow ? 16 : Math.max(48, w * 0.06));
  const laneH = Math.min(54, (narrow ? h * 0.28 : h * 0.3) / lanes);
  // under the copy on every screen, with room for the minute ruler below
  const top = narrow ? h * 0.6 : Math.max(h * 0.56, h - laneH * lanes - 96);
  return { w, h, cx, cy, ro, ri: ro * 0.3, laneX0, laneX1, laneY: Array.from({ length: lanes }, (_, i) => top + laneH * (i + 0.5)), laneH };
}

function spiral(l: Layout, f: number): [number, number] {
  const a = -Math.PI / 2 + f * TURNS * Math.PI * 2;
  const r = l.ro - f * (l.ro - l.ri);
  return [l.cx + r * Math.cos(a), l.cy + r * Math.sin(a)];
}

/** Per-turn progress: the outer end of the groove (the start of the meeting) unwinds first. */
const local = (p: number, f: number) => smooth(clamp01((p - 0.08 - 0.42 * f) / 0.36));

function draw(ctx: CanvasRenderingContext2D, l: Layout, side: Side, p: number, head: number, hex: string[], ink: string, faint: string) {
  const { w, h } = l;
  ctx.clearRect(0, 0, w, h);
  const lanes = side.speakers.map((s) => s.track);
  const settled = smooth(clamp01((p - 0.78) / 0.18));

  // the bare groove, fading as it unwinds
  const bare = 1 - smooth(clamp01(p / 0.5));
  if (bare > 0.01) {
    ctx.beginPath();
    for (let i = 0; i <= 900; i++) {
      const [x, y] = spiral(l, i / 900);
      if (i) ctx.lineTo(x, y);
      else ctx.moveTo(x, y);
    }
    ctx.strokeStyle = faint;
    ctx.globalAlpha = bare;
    ctx.lineWidth = 1;
    ctx.stroke();
    ctx.globalAlpha = 1;
  }

  // lane guides, names and the minute ruler arrive as the turns settle
  if (settled > 0.01) {
    ctx.globalAlpha = settled;
    ctx.font = `500 13px "Recursive Variable", system-ui, sans-serif`;
    ctx.textBaseline = "middle";
    side.speakers.forEach((s, i) => {
      const y = l.laneY[i];
      ctx.fillStyle = faint;
      ctx.fillRect(l.laneX0, y + l.laneH / 2 - 0.5, l.laneX1 - l.laneX0, 1);
      ctx.fillStyle = hex[side.colours.get(s.track) ?? 7];
      ctx.beginPath();
      ctx.arc(l.laneX0 - 60, y, 4, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = ink;
      ctx.textAlign = "left";
      ctx.fillText(s.name ?? s.label, l.laneX0 - 50, y);
    });
    ctx.fillStyle = faint;
    ctx.textAlign = "center";
    ctx.font = `400 11px "Recursive Variable", system-ui, sans-serif`;
    const bottom = l.laneY[l.laneY.length - 1] + l.laneH / 2 + 18;
    for (let m = 0; m * 60 <= side.duration; m++) {
      const x = l.laneX0 + ((m * 60) / side.duration) * (l.laneX1 - l.laneX0);
      ctx.fillText(timecode(m * 60), x, bottom);
    }
    ctx.globalAlpha = 1;
  }

  // every turn of speech: an arc of groove that straightens into its speaker's lane
  ctx.lineCap = "round";
  const span = l.laneX1 - l.laneX0;
  const grooveW = Math.max(2, ((l.ro - l.ri) / TURNS) * 0.55);
  for (const u of side.utterances) {
    const f0 = u.t_start / side.duration;
    const f1 = u.t_end / side.duration;
    const q = local(p, (f0 + f1) / 2);
    const lane = Math.max(0, lanes.indexOf(u.speaker));
    const y = l.laneY[lane];
    const steps = Math.max(3, Math.ceil((f1 - f0) * TURNS * 64));
    const width = grooveW + (Math.min(l.laneH * 0.42, 18) - grooveW) * q;
    // round caps overhang by half the line width; pull the ends in so neighbouring turns keep a gap
    const len = (f1 - f0) * span;
    const inset = Math.min((width / 2) * q, Math.max(0, len / 2 - 0.5)) + q;
    ctx.beginPath();
    for (let i = 0; i <= steps; i++) {
      const f = f0 + ((f1 - f0) * i) / steps;
      const [sx, sy] = spiral(l, f);
      const lx = l.laneX0 + f * span + (i === 0 ? inset : i === steps ? -inset : 0);
      // a little lift mid-flight, so the turns peel off rather than slide
      const lift = Math.sin(q * Math.PI) * l.laneH * 0.9;
      const x = sx + (lx - sx) * q;
      const yy = sy + (y - sy) * q - lift;
      if (i) ctx.lineTo(x, yy);
      else ctx.moveTo(x, yy);
    }
    ctx.strokeStyle = hex[side.colours.get(u.speaker) ?? 7];
    ctx.lineWidth = width;
    ctx.stroke();
  }

  // the stylus: where the record is playing right now, on whichever form the timeline has
  const f = clamp01(head / side.duration);
  const q = local(p, f);
  const [sx, sy] = spiral(l, f);
  const x = sx + (l.laneX0 + f * span - sx) * q;
  const top = l.laneY[0] - l.laneH / 2;
  const bottom = l.laneY[l.laneY.length - 1] + l.laneH / 2;
  ctx.fillStyle = ink;
  if (q > 0.98) {
    ctx.fillRect(x - 0.75, top - 6, 1.5, bottom - top + 12);
  } else {
    const yy = sy + ((top + bottom) / 2 - sy) * q;
    ctx.beginPath();
    ctx.arc(x, yy, 4.5, 0, Math.PI * 2);
    ctx.fill();
  }
}

/** The groove is the timeline: scroll to unwind the record into the multitrack. */
export default function Unspool({ deck }: { deck: Deck }) {
  const { side: sideIdx } = useDeckState(deck);
  const sectionRef = useRef<HTMLElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const section = sectionRef.current;
    const canvas = canvasRef.current;
    if (!section || !canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const css = getComputedStyle(document.documentElement);
    const ink = css.getPropertyValue("--ink").trim();
    const faint = css.getPropertyValue("--line-strong").trim();
    const hex = speakerHex();
    let l: Layout | null = null;
    let raf = 0;
    let visible = false;

    const resize = () => {
      const r = canvas.getBoundingClientRect();
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.round(r.width * dpr);
      canvas.height = Math.round(r.height * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      l = layout(r.width, r.height, deck.current.speakers.length, r.width < 760);
    };
    const progress = () => {
      if (reduced) return 1;
      const r = section.getBoundingClientRect();
      const run = r.height - window.innerHeight;
      return run > 0 ? clamp01(-r.top / run) : 1;
    };
    const frame = () => {
      if (l) draw(ctx, l, deck.current, progress(), deck.time(), hex, ink, faint);
      if (visible) raf = requestAnimationFrame(frame);
    };
    const ro = new ResizeObserver(() => {
      resize();
      frame();
    });
    ro.observe(canvas);
    const io = new IntersectionObserver(([e]) => {
      visible = e.isIntersecting;
      cancelAnimationFrame(raf);
      if (visible) raf = requestAnimationFrame(frame);
    });
    io.observe(section);
    return () => {
      ro.disconnect();
      io.disconnect();
      cancelAnimationFrame(raf);
    };
  }, [deck, sideIdx]);

  return (
    <section ref={sectionRef} className="unspool" id="how" aria-labelledby="unspool-title">
      <div className="unspool-stick">
        <canvas ref={canvasRef} className="unspool-canvas" aria-hidden="true" />
        <div className="unspool-copy" data-reveal>
          <h2 id="unspool-title" className="l-h2">
            The groove is the timeline.
          </h2>
          <p className="l-lede">
            Each band of the record is one turn of speech, in the colour of whoever said it. Unwind it and you have the view the whole app is
            built on: one lane per speaker, a block wherever they spoke.
          </p>
        </div>
      </div>
    </section>
  );
}
