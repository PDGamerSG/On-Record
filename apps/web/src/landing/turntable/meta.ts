// Written by scripts/blender/build_turntable.py: where the spindle, pivot and stylus are, in Blender
// units (Z up, 1 unit = 100 mm). The hero converts to three's Y-up frame where it needs to.
import raw from "./meta.json";

export interface TurntableMeta {
  unit_mm: number;
  spindle: [number, number];
  pivot: [number, number];
  tip_local: [number, number, number];
  rest_angle: number;
  record_r: number;
  groove_out: number;
  groove_in: number;
  label_r: number;
  record_top: number;
}

export const META = raw as unknown as TurntableMeta;

/** Pivot angle (about the vertical axis) that puts the stylus at radius r from the spindle.
 *  Same maths as aim() in the Blender script. */
export function aimArm(m: TurntableMeta, r: number): number {
  const [sx, sy] = m.spindle;
  const [px, py] = m.pivot;
  const [lx, ly] = m.tip_local;
  const dx = px - sx;
  const dy = py - sy;
  const dist = Math.hypot(dx, dy);
  const len = Math.hypot(lx, ly);
  const c = (r * r - dist * dist - len * len) / (2 * len * dist);
  const base = Math.atan2(-dy, -dx) - Math.atan2(ly, lx);
  const spread = Math.acos(Math.max(-1, Math.min(1, -c)));
  const wrap = (a: number) => Math.atan2(Math.sin(a), Math.cos(a));
  const a = base + spread;
  const b = base - spread;
  return Math.abs(wrap(a - m.rest_angle)) < Math.abs(wrap(b - m.rest_angle)) ? a : b;
}
