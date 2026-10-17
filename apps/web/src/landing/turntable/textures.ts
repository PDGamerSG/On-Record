// Canvas textures for the record, pressed from a meeting. All three groove maps share the record's
// planar UV from the Blender build: the canvas is a top-down view of the whole disc, centre in the
// middle, edge at the canvas edge. 00:00 sits on the outer groove; the last word on the inner one.
import * as THREE from "three";
import { timecode } from "../../lib/format";
import type { Side } from "../sides";
import type { TurntableMeta } from "./meta";

const VINYL = "#0b0b0d";

function canvas(size: number): [HTMLCanvasElement, CanvasRenderingContext2D] {
  const c = document.createElement("canvas");
  c.width = c.height = size;
  return [c, c.getContext("2d")!];
}

function texture(c: HTMLCanvasElement, srgb: boolean): THREE.CanvasTexture {
  const t = new THREE.CanvasTexture(c);
  t.flipY = false; // glTF UV convention
  t.colorSpace = srgb ? THREE.SRGBColorSpace : THREE.NoColorSpace;
  t.anisotropy = 8;
  t.generateMipmaps = true;
  t.minFilter = THREE.LinearMipmapLinearFilter;
  return t;
}

/** Radius on the record (Blender units) for a moment in the meeting. */
export function radiusAt(meta: TurntableMeta, side: Side, t: number): number {
  const f = Math.min(1, Math.max(0, t / side.duration));
  return meta.groove_out - f * (meta.groove_out - meta.groove_in);
}

export function timeAtRadius(meta: TurntableMeta, side: Side, r: number): number | null {
  if (r < meta.groove_in - 0.01 || r > meta.groove_out + 0.01) return null;
  const f = (meta.groove_out - r) / (meta.groove_out - meta.groove_in);
  return Math.min(side.duration, Math.max(0, f * side.duration));
}

export interface GrooveMaps {
  map: THREE.CanvasTexture;
  /** roughness in G, metalness in B (three's convention) */
  orm: THREE.CanvasTexture;
}

/** Spoken bands are tinted metal, so a speaker's colour flashes where the light rakes across their
 *  turn; pauses stay as glossy black lands, like the gaps between tracks. */
export function grooveMaps(meta: TurntableMeta, side: Side, hex: string[], size = 2048): GrooveMaps {
  const [cc, c] = canvas(size);
  const [oc, o] = canvas(size);
  const mid = size / 2;
  const px = (r: number) => (r / meta.record_r) * mid;

  c.fillStyle = VINYL;
  c.fillRect(0, 0, size, size);
  o.fillStyle = "rgb(255, 36, 0)"; // smooth, non-metal
  o.fillRect(0, 0, size, size);

  const band = (ctx: CanvasRenderingContext2D, t0: number, t1: number, style: string) => {
    const r0 = px(radiusAt(meta, side, t0));
    const r1 = px(radiusAt(meta, side, t1));
    ctx.beginPath();
    ctx.arc(mid, mid, (r0 + r1) / 2, 0, Math.PI * 2);
    ctx.lineWidth = Math.max(1, Math.abs(r0 - r1));
    ctx.strokeStyle = style;
    ctx.stroke();
  };

  // the whole groove area is cut, even where nobody spoke
  band(c, 0, side.duration, "#101013");
  band(o, 0, side.duration, "rgb(255, 46, 0)");
  // the colour sits under a dark film, so a band reads as black vinyl until the light rakes across it
  for (const u of side.utterances) {
    const colour = hex[side.colours.get(u.speaker) ?? 7];
    band(c, u.t_start, u.t_end, colour);
    band(o, u.t_start, u.t_end, "rgb(255, 84, 235)");
  }
  c.globalCompositeOperation = "multiply";
  band(c, 0, side.duration, "rgb(150, 150, 156)");
  c.globalCompositeOperation = "source-over";

  // the groove walls: fine rings, darker on one wall than the other
  const inner = px(meta.groove_in);
  const outer = px(meta.groove_out);
  for (let r = inner; r <= outer; r += 2.25) {
    c.beginPath();
    c.arc(mid, mid, r, 0, Math.PI * 2);
    c.lineWidth = 0.9;
    c.strokeStyle = "rgba(0, 0, 0, 0.42)";
    c.stroke();
    o.beginPath();
    o.arc(mid, mid, r, 0, Math.PI * 2);
    o.lineWidth = 0.9;
    o.strokeStyle = "rgba(0, 140, 0, 0.35)";
    o.stroke();
  }
  // lead-in and run-out: a few wider spirals of plain vinyl
  for (const r of [meta.groove_out + 0.012, meta.groove_in - 0.02, meta.groove_in - 0.035]) {
    c.beginPath();
    c.arc(mid, mid, px(r), 0, Math.PI * 2);
    c.lineWidth = 1.2;
    c.strokeStyle = "rgba(255, 255, 255, 0.05)";
    c.stroke();
  }
  return { map: texture(cc, true), orm: texture(oc, false) };
}

/** MeshPhysicalMaterial.anisotropyMap for the grooves. Highlights stretch along this direction, and a
 *  groove spreads light across itself, so it points out from the centre: the bow-tie sheen of real vinyl. */
export function grooveDirection(meta: TurntableMeta, size = 512): THREE.DataTexture {
  const data = new Uint8Array(size * size * 4);
  const mid = size / 2;
  const inner = (meta.groove_in - 0.06) / meta.record_r;
  const outer = (meta.groove_out + 0.03) / meta.record_r;
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const dx = (x + 0.5 - mid) / mid;
      const dy = (y + 0.5 - mid) / mid;
      const r = Math.hypot(dx, dy) || 1;
      const i = (y * size + x) * 4;
      data[i] = Math.round((0.5 + 0.5 * (dx / r)) * 255);
      data[i + 1] = Math.round((0.5 + 0.5 * (dy / r)) * 255);
      data[i + 2] = r >= inner && r <= outer ? 255 : 90;
      data[i + 3] = 255;
    }
  }
  const t = new THREE.DataTexture(data, size, size, THREE.RGBAFormat);
  t.flipY = false;
  t.colorSpace = THREE.NoColorSpace;
  t.magFilter = THREE.LinearFilter;
  t.minFilter = THREE.LinearMipmapLinearFilter;
  t.generateMipmaps = true;
  t.needsUpdate = true;
  return t;
}

function ringText(ctx: CanvasRenderingContext2D, text: string, cx: number, cy: number, r: number, start: number) {
  const chars = [...text];
  const widths = chars.map((ch) => ctx.measureText(ch).width);
  const total = widths.reduce((a, b) => a + b, 0);
  let a = start - total / r / 2;
  for (let i = 0; i < chars.length; i++) {
    const w = widths[i];
    a += w / r / 2;
    ctx.save();
    ctx.translate(cx + r * Math.cos(a), cy + r * Math.sin(a));
    ctx.rotate(a + Math.PI / 2);
    ctx.fillText(chars[i], 0, 0);
    ctx.restore();
    a += w / r / 2;
  }
}

/** The paper label. The canvas covers only the label disc; the material maps it there with repeat/offset. */
export function labelTexture(meta: TurntableMeta, side: Side, hex: string[], size = 1024): THREE.CanvasTexture {
  const [cv, c] = canvas(size);
  const mid = size / 2;
  const R = mid;
  const k = R / meta.label_r; // px per Blender unit on the label

  // paper, with a little tooth
  c.fillStyle = "#ECE9E2";
  c.fillRect(0, 0, size, size);
  const img = c.getImageData(0, 0, size, size);
  for (let i = 0; i < img.data.length; i += 4) {
    const n = (Math.random() - 0.5) * 10;
    img.data[i] += n;
    img.data[i + 1] += n;
    img.data[i + 2] += n;
  }
  c.putImageData(img, 0, 0);
  const shade = c.createRadialGradient(mid, mid, R * 0.2, mid, mid, R);
  shade.addColorStop(0, "rgba(0,0,0,0)");
  shade.addColorStop(1, "rgba(60,48,30,0.10)");
  c.fillStyle = shade;
  c.fillRect(0, 0, size, size);

  const ink = "#121318";
  c.fillStyle = ink;
  c.strokeStyle = ink;
  c.textAlign = "center";
  c.textBaseline = "middle";

  // rim lettering
  c.lineWidth = 2;
  c.beginPath();
  c.arc(mid, mid, R * 0.955, 0, Math.PI * 2);
  c.stroke();
  c.font = `500 ${Math.round(size * 0.03)}px "Recursive Variable", sans-serif`;
  c.fillStyle = "#3a3d44";
  const rim = `ON RECORD  ·  SIDE ${side.letter}  ·  33⅓ RPM  ·  ${side.speakers.length} SPEAKERS  ·  ${timecode(side.duration)}  ·  DEMO MEETING  ·  `;
  ringText(c, rim.toUpperCase(), mid, mid, R * 0.885, -Math.PI / 2);

  // talk time: one arc per speaker, clockwise from 12 o'clock, longest first
  const speakers = [...side.speakers].sort((a, b) => b.talk_time_s - a.talk_time_s);
  const total = speakers.reduce((s, x) => s + x.talk_time_s, 0) || 1;
  let a0 = -Math.PI / 2;
  c.lineCap = "butt";
  for (const s of speakers) {
    const span = (s.talk_time_s / total) * Math.PI * 2;
    c.beginPath();
    c.arc(mid, mid, R * 0.72, a0 + 0.025, a0 + span - 0.025);
    c.lineWidth = R * 0.055;
    c.strokeStyle = hex[side.colours.get(s.track) ?? 7];
    c.stroke();
    a0 += span;
  }

  // title above the spindle, side letter and duration below
  c.fillStyle = ink;
  const words = side.title.split(" ");
  const split = Math.ceil(words.length / 2);
  const lines = [words.slice(0, split).join(" "), words.slice(split).join(" ")];
  c.font = `400 ${Math.round(size * 0.068)}px "Newsreader Variable", Georgia, serif`;
  lines.forEach((l, i) => c.fillText(l, mid, mid - R * 0.36 + i * size * 0.072));

  c.font = `650 ${Math.round(size * 0.052)}px "Recursive Variable", sans-serif`;
  c.fillText(side.letter, mid, mid + R * 0.3);
  c.font = `500 ${Math.round(size * 0.026)}px "Recursive Variable", sans-serif`;
  c.fillStyle = "#4a4e57";
  c.fillText(`SIDE ${side.letter}  ·  ${timecode(side.duration)}`, mid, mid + R * 0.44);

  // spindle hole and the pressing ring around it
  c.beginPath();
  c.arc(mid, mid, 0.036 * k * 1.15, 0, Math.PI * 2);
  c.fillStyle = "#0a0a0b";
  c.fill();
  c.beginPath();
  c.arc(mid, mid, R * 0.17, 0, Math.PI * 2);
  c.lineWidth = 1.5;
  c.strokeStyle = "rgba(18,19,24,0.35)";
  c.stroke();

  const t = texture(cv, true);
  const s = meta.record_r / meta.label_r;
  t.wrapS = t.wrapT = THREE.ClampToEdgeWrapping;
  t.repeat.set(s, s);
  t.offset.set(0.5 - 0.5 * s, 0.5 - 0.5 * s);
  return t;
}
