// Citation markers in document answers: [d:<chunk id>] for document passages and [u:<utterance id>] for meeting lines,
// occasionally several in one bracket ("[d:a, d:b]").
export type CiteKind = "d" | "u";
export interface CiteRef {
  kind: CiteKind;
  id: string;
}

export const MARKER = /\[((?:d|u):[^\]]+)\]/g;

/** The references in a marker body: "d:doc-x:c0005" or "d:doc-x:c0005, u:meeting:u00012". */
export function markerRefs(body: string): CiteRef[] {
  const out: CiteRef[] = [];
  let kind: CiteKind = body.startsWith("u:") ? "u" : "d";
  for (const raw of body.split(/[,;]\s*/)) {
    const part = raw.trim();
    if (!part) continue;
    const m = /^(d|u):(.+)$/.exec(part);
    if (m) kind = m[1] as CiteKind;
    out.push({ kind, id: m ? m[2] : part });
  }
  return out;
}

/** Every reference cited in a text, in order of first appearance. */
export function citedRefs(text: string): CiteRef[] {
  const seen = new Set<string>();
  const out: CiteRef[] = [];
  for (const m of text.matchAll(MARKER)) {
    for (const ref of markerRefs(m[1])) {
      const key = `${ref.kind}:${ref.id}`;
      if (!seen.has(key)) {
        seen.add(key);
        out.push(ref);
      }
    }
  }
  return out;
}
