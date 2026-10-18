// Light rendering for model-written text: paragraphs, "-"/"*"/"1." lists, **bold**, and [d:...]/[u:...] citation markers.
import type { ReactNode } from "react";
import { MARKER, markerRefs, type CiteRef } from "./citations";

const BULLET = /^\s*(?:[-*•]|\d+[.)])\s+/;

export type CiteRenderer = (ref: CiteRef, key: string) => ReactNode;

function withCites(text: string, keyBase: string, renderCite?: CiteRenderer): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  for (const m of text.matchAll(MARKER)) {
    const at = m.index ?? 0;
    // the space before a marker belongs to the chip, so "deadline [d:..]." doesn't leave a gap before the full stop
    if (at > last) out.push(text.slice(last, at).replace(/\s+$/, at > 0 ? " " : ""));
    if (renderCite) markerRefs(m[1]).forEach((ref, i) => out.push(renderCite(ref, `${keyBase}-${at}-${i}`)));
    last = at + m[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

function Inline({ text, renderCite, keyBase }: { text: string; renderCite?: CiteRenderer; keyBase: string }) {
  const parts = text.split(/\*\*(.+?)\*\*/g);
  return (
    <>
      {parts.map((part, i) => {
        const clean = i % 2 ? part : part.replace(/\*\*/g, "");
        const nodes = withCites(clean, `${keyBase}-${i}`, renderCite);
        return i % 2 ? <strong key={i}>{nodes}</strong> : <span key={i}>{nodes}</span>;
      })}
    </>
  );
}

/** Consecutive bullet lines become one list; other consecutive lines become one paragraph. */
function segments(text: string): { list: boolean; lines: string[] }[] {
  const out: { list: boolean; lines: string[] }[] = [];
  for (const block of text.trim().split(/\n\s*\n/)) {
    let cur: { list: boolean; lines: string[] } | null = null;
    for (const line of block.split("\n")) {
      if (!line.trim()) continue;
      const list = BULLET.test(line);
      if (!cur || cur.list !== list) {
        cur = { list, lines: [] };
        out.push(cur);
      }
      cur.lines.push(line);
    }
  }
  return out;
}

export default function RichText({ text, renderCite, className }: { text: string; renderCite?: CiteRenderer; className?: string }) {
  return (
    <div className={className}>
      {segments(text).map((seg, b) => {
        if (seg.list) {
          const items = seg.lines.map((l, i) => (
            <li key={i}>
              <Inline text={l.replace(BULLET, "")} renderCite={renderCite} keyBase={`${b}-${i}`} />
            </li>
          ));
          return /^\s*\d/.test(seg.lines[0]) ? <ol key={b}>{items}</ol> : <ul key={b}>{items}</ul>;
        }
        return (
          <p key={b}>
            <Inline text={seg.lines.join("\n")} renderCite={renderCite} keyBase={`${b}`} />
          </p>
        );
      })}
    </div>
  );
}
