// The bundled demo: the two scripted Kitepost meetings, served from memory with the same shape as the API.
// Writes (ticking an action item, naming a speaker) change the in-memory copy only and reset on reload.
// The Ask answers are worked out here from the same data with simple matching, and say so in `provider`.
import type {
  ActionItem,
  AskResult,
  Decision,
  GraphLink,
  GraphNode,
  Health,
  Hit,
  MeetingDetail,
  MeetingSummary,
  Person,
  Speaker,
  Subgraph,
  Turn,
  Utterance,
  WhoKnows,
} from "../types";
import type { Api } from "../client";
import { ApiError } from "../base";
import { brand } from "../../lib/brand";
import raw from "./fixtures.json";

interface Entity {
  id: string;
  name: string;
  kind: string;
  utterances: string[];
}

interface DemoDetail extends MeetingDetail {
  entities: Entity[];
  topic_links: [string, string][];
  audio: string;
}

interface Fixtures {
  meetings: MeetingSummary[];
  details: Record<string, DemoDetail>;
  people: (Person & { role?: string })[];
}

const db: Fixtures = structuredClone(raw as unknown as Fixtures);
const sessions = new Map<string, Turn[]>();
const subject = new Map<string, ActionItem>();

const DEMO_MODEL = "gemma4:12b-it-qat";
const NEEDS_SERVER = "This preview runs on the bundled demo meetings. Start the API to record or upload.";

function wait<T>(value: T, ms = 140 + Math.random() * 160): Promise<T> {
  return new Promise((resolve) => window.setTimeout(() => resolve(structuredClone(value)), ms));
}

function detail(id: string): DemoDetail {
  const d = db.details[id];
  if (!d) throw new ApiError(404, "Meeting not found");
  return d;
}

const allDetails = () => Object.values(db.details);
const allUtterances = () => allDetails().flatMap((d) => d.utterances);
const allItems = () => allDetails().flatMap((d) => d.action_items);
const allDecisions = () => allDetails().flatMap((d) => d.decisions);
const titleOf = (meetingId: string) => db.details[meetingId]?.meeting.title ?? "";

const STOP = new Set(
  "a an and are at be but by can did do does for from has have he her his how i in is it its me my of on or our she so that the their them then there they this to us was we were what when where which who why will with you your about any also just".split(
    " ",
  ),
);

function terms(text: string): string[] {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, " ")
    .split(/\s+/)
    .filter((w) => w.length > 1 && !STOP.has(w))
    .map((w) => w.replace(/(ing|ed|es|s)$/, ""));
}

function toHit(u: Utterance, score: number, via: Hit["via"] = "fulltext"): Hit {
  return {
    utterance_id: u.id,
    meeting_id: u.meeting_id,
    meeting_title: titleOf(u.meeting_id),
    speaker: u.speaker,
    speaker_name: u.speaker_name,
    t_start: u.t_start,
    t_end: u.t_end,
    text: u.text,
    score,
    via,
  };
}

function searchHits(q: string, meetingId?: string, limit = 8): Hit[] {
  const want = terms(q);
  if (!want.length) return [];
  return allUtterances()
    .filter((u) => !meetingId || u.meeting_id === meetingId)
    .map((u) => {
      const have = new Set(terms(u.text));
      const score = want.reduce((n, w) => n + (have.has(w) ? 1 : 0), 0) / want.length;
      return { u, score };
    })
    .filter((x) => x.score > 0)
    .sort((a, b) => b.score - a.score || a.u.t_start - b.u.t_start)
    .slice(0, limit)
    .map(({ u, score }) => toHit(u, Number(score.toFixed(3))));
}

function evidenceHits(ids: string[]): Hit[] {
  const byId = new Map(allUtterances().map((u) => [u.id, u]));
  return ids.flatMap((id) => {
    const u = byId.get(id);
    return u ? [toHit(u, 1, "graph")] : [];
  });
}

function stats(): Record<string, number> {
  const d = allDetails();
  const speakers = d.reduce((n, x) => n + x.speakers.length, 0);
  const utterances = d.reduce((n, x) => n + x.utterances.length, 0);
  const decisions = d.reduce((n, x) => n + x.decisions.length, 0);
  const items = d.reduce((n, x) => n + x.action_items.length, 0);
  const topics = d.reduce((n, x) => n + x.topics.length, 0);
  const links = d.reduce((n, x) => n + x.topic_links.length, 0);
  const evidence = allDecisions().reduce((n, x) => n + x.evidence.length, 0) + allItems().reduce((n, x) => n + x.evidence.length, 0);
  return {
    Meeting: d.length,
    Utterance: utterances,
    Speaker: speakers,
    Person: db.people.length,
    Decision: decisions,
    ActionItem: items,
    Topic: topics,
    relationships: utterances * 3 + speakers + links + evidence + items,
  };
}

function subgraph(q: { meeting_id?: string; utterance_ids?: string[] }): Subgraph {
  const nodes = new Map<string, GraphNode>();
  const links: GraphLink[] = [];
  const add = (n: GraphNode) => nodes.set(n.id, n);
  const link = (source: string, target: string, type: string) => {
    if (nodes.has(source) && nodes.has(target)) links.push({ source, target, type });
  };
  const only = q.utterance_ids?.length ? new Set(q.utterance_ids) : null;
  const persons = new Map(db.people.map((p) => [p.name, p]));

  for (const d of allDetails()) {
    if (q.meeting_id && d.meeting.id !== q.meeting_id) continue;
    const utts = only ? d.utterances.filter((u) => only.has(u.id)) : d.utterances;
    if (only && !utts.length) continue;
    const mid = d.meeting.id;
    add({ id: mid, label: d.meeting.title, kind: "Meeting" });
    for (const s of d.speakers) {
      if (only && !utts.some((u) => u.speaker === s.track)) continue;
      const sid = `${mid}:${s.track}`;
      add({ id: sid, label: s.name ?? s.label, kind: "Speaker", track: s.track, color_idx: s.color_idx });
      const p = s.name ? persons.get(s.name) : undefined;
      if (p) {
        add({ id: p.id, label: p.name, kind: "Person" });
        link(sid, p.id, "IS");
      }
    }
    let prev: string | null = null;
    for (const u of utts) {
      add({ id: u.id, label: u.text.length > 64 ? `${u.text.slice(0, 62)}…` : u.text, kind: "Utterance", speaker: u.speaker, t_start: u.t_start });
      link(mid, u.id, "HAS_UTTERANCE");
      link(u.id, `${mid}:${u.speaker}`, "SPOKEN_BY");
      if (prev && !only) link(prev, u.id, "NEXT");
      prev = u.id;
    }
    const kept = new Set(utts.map((u) => u.id));
    for (const x of d.decisions) {
      if (only && !x.evidence.some((e) => kept.has(e))) continue;
      add({ id: x.id, label: x.text, kind: "Decision", status: x.status });
      x.evidence.forEach((e) => link(x.id, e, "EVIDENCED_BY"));
    }
    for (const a of d.action_items) {
      if (only && !a.evidence.some((e) => kept.has(e))) continue;
      add({ id: a.id, label: a.text, kind: "ActionItem", status: a.status });
      a.evidence.forEach((e) => link(a.id, e, "EVIDENCED_BY"));
      if (a.owner_track) link(a.id, `${mid}:${a.owner_track}`, "ASSIGNED_TO");
    }
    for (const t of d.topics) add({ id: t.id, label: t.name, kind: "Topic", mentions: t.mentions });
    for (const [u, t] of d.topic_links) link(u, t, "MENTIONS");
    for (const e of d.entities) {
      if (only && !e.utterances.some((u) => kept.has(u))) continue;
      add({ id: e.id, label: e.name, kind: "Entity", entity_kind: e.kind });
      e.utterances.forEach((u) => link(u, e.id, "MENTIONS"));
    }
  }
  // Supersession crosses meetings, so link it once every decision is in.
  for (const x of allDecisions()) if (x.supersedes) link(x.id, x.supersedes, "SUPERSEDES");
  // Topics with no mention in the kept utterances are noise in an evidence view.
  if (only) {
    const used = new Set(links.flatMap((l) => [l.source, l.target]));
    for (const [id, n] of nodes) if (n.kind === "Topic" && !used.has(id)) nodes.delete(id);
  }
  return { nodes: [...nodes.values()], links };
}

// ---- Ask -----------------------------------------------------------------------------------------

interface Draft {
  answer: string;
  citations: Hit[];
  tools: AskResult["tool_trace"];
  cypher: string[];
  actions?: AskResult["actions"];
}

const person = (q: string) => db.people.find((p) => new RegExp(`\\b${p.name}\\b`, "i").test(q));

function listItemsFor(name: string): Draft {
  const items = allItems().filter((a) => a.owner === name);
  const open = items.filter((a) => a.status === "open");
  const lines = items.map((a) => `${a.text.charAt(0).toLowerCase()}${a.text.slice(1)}${a.due ? ` (due ${a.due})` : ""}${a.status === "done" ? ", already done" : ""}`);
  const answer = items.length
    ? `${name} committed to ${items.length === 1 ? "one thing" : `${items.length} things`}: ${lines.join("; ")}. ${open.length} ${open.length === 1 ? "is" : "are"} still open.`
    : `I couldn't find an action item assigned to ${name}.`;
  return {
    answer,
    citations: evidenceHits(items.flatMap((a) => a.evidence)).slice(0, 4),
    tools: [{ tool: "list_action_items", args: { owner: name }, result_count: items.length, ms: 38 }],
    cypher: [
      `MATCH (a:ActionItem)-[:ASSIGNED_TO]->(:Speaker)-[:IS]->(p:Person {name: $owner})\nOPTIONAL MATCH (a)-[:EVIDENCED_BY]->(u:Utterance)\nRETURN a, collect(u.id) AS evidence ORDER BY a.created_at`,
    ],
  };
}

function decisionsAnswer(q: string, meetingId?: string): Draft {
  const pool = allDecisions().filter((d) => !meetingId || d.meeting_id === meetingId);
  const want = terms(q).filter((w) => !["decid", "decision", "decide", "agre", "lock"].includes(w));
  const scored = want.length
    ? pool.filter((d) => {
        const have = new Set(terms(d.text));
        return want.some((w) => have.has(w));
      })
    : pool;
  const chosen = (scored.length ? scored : pool).filter((d) => d.status === "active").slice(0, 3);
  const superseded = pool.filter((d) => d.status === "superseded" && chosen.some((c) => c.supersedes === d.id));
  let answer = chosen.length
    ? `${chosen.length === 1 ? "The standing decision" : "The standing decisions"}: ${chosen.map((d) => `${d.text} (${d.proposed_by ?? "the room"}, ${titleOf(d.meeting_id)})`).join("; ")}.`
    : "No decision matches that yet.";
  if (superseded.length) answer += ` This replaced an earlier call: ${superseded.map((d) => d.text).join("; ")}.`;
  return {
    answer,
    citations: evidenceHits(chosen.flatMap((d) => d.evidence)).slice(0, 4),
    tools: [{ tool: "list_decisions", args: meetingId ? { meeting_id: meetingId } : {}, result_count: chosen.length, ms: 31 }],
    cypher: [
      `MATCH (d:Decision {status: 'active'})-[:EVIDENCED_BY]->(u:Utterance)<-[:HAS_UTTERANCE]-(m:Meeting)\nOPTIONAL MATCH (d)-[:SUPERSEDES]->(old:Decision)\nRETURN d, m.title, collect(u.id), old`,
    ],
  };
}

function completeAnswer(item: ActionItem): Draft {
  item.status = "done";
  item.done_at = Date.now();
  return {
    answer: `Done. I marked "${item.text}" as complete for ${item.owner ?? "its owner"}.`,
    citations: evidenceHits(item.evidence).slice(0, 2),
    tools: [{ tool: "complete_action_item", args: { id: item.id }, result_count: 1, ms: 22 }],
    cypher: [`MATCH (a:ActionItem {id: $id}) SET a.status = 'done', a.done_at = timestamp() RETURN a`],
    actions: [{ type: "refresh", what: "action_items" }],
  };
}

function searchAnswer(q: string, meetingId?: string): Draft {
  const hits = searchHits(q, meetingId, 4);
  const top = hits[0];
  const answer = top
    ? `${top.speaker_name ?? "Someone"} covered this in ${top.meeting_title}: "${top.text}"${hits[1] ? ` ${hits[1].speaker_name ?? "Another speaker"} added: "${hits[1].text}"` : ""}`
    : "Nothing in the recorded meetings matches that. Try a name, a number, or a topic such as pricing or launch.";
  return {
    answer,
    citations: hits,
    tools: [{ tool: "search_meetings", args: { query: q, ...(meetingId ? { meeting_id: meetingId } : {}) }, result_count: hits.length, ms: 54 }],
    cypher: [
      `CALL db.idx.fulltext.queryNodes('Utterance', $q) YIELD node, score\nMATCH (node)-[:SPOKEN_BY]->(s:Speaker)\nRETURN node, s, score ORDER BY score DESC LIMIT 8`,
      `CALL db.idx.vector.queryNodes('Utterance', 'embedding', 8, vecf32($vec)) YIELD node, score RETURN node, score`,
    ],
  };
}

function draftAnswer(session: string, q: string, meetingId?: string): Draft {
  const p = person(q);
  const last = subject.get(session);
  if (/\b(mark|set|tick)\b.*\b(done|complete|finished)\b|\bit'?s done\b/i.test(q) && last) return completeAnswer(last);
  if (/\b(when|due|deadline)\b/i.test(q) && !p && last) {
    return {
      answer: `${last.owner} said it would be done ${last.due ?? "without a firm date"}. It came up in ${last.meeting_title}.`,
      citations: evidenceHits(last.evidence),
      tools: [{ tool: "list_action_items", args: { id: last.id }, result_count: 1, ms: 19 }],
      cypher: [`MATCH (a:ActionItem {id: $id})-[:EVIDENCED_BY]->(u:Utterance) RETURN a.due, u`],
    };
  }
  if (p && /\b(commit|promise|own|owe|action|task|todo|working on|doing|agree)/i.test(q)) {
    const d = listItemsFor(p.name);
    const first = allItems().find((a) => a.owner === p.name && a.status === "open");
    if (first) subject.set(session, first);
    return d;
  }
  if (/\b(decid|decision|agreed|settled|lock|final)/i.test(q)) return decisionsAnswer(q, meetingId);
  if (/\b(summar|recap|what happened|overview)/i.test(q)) {
    const ms = meetingId ? [detail(meetingId)] : allDetails();
    return {
      answer: ms.map((d) => `${d.meeting.title}: ${d.meeting.summary ?? ""}`).join(" "),
      citations: evidenceHits(ms.flatMap((d) => d.decisions.slice(0, 1).flatMap((x) => x.evidence))).slice(0, 3),
      tools: [{ tool: "summarize_meeting", args: meetingId ? { meeting_id: meetingId } : {}, result_count: ms.length, ms: 47 }],
      cypher: [`MATCH (m:Meeting) WHERE $id IS NULL OR m.id = $id RETURN m.title, m.summary`],
    };
  }
  return searchAnswer(q, meetingId);
}

function respond(session: string, question: string, meetingId?: string, transcript: string | null = null): AskResult {
  const started = performance.now();
  const d = draftAnswer(session, question, meetingId);
  const turns = sessions.get(session) ?? [];
  const now = Date.now();
  turns.push({ role: "user", text: question, at: now, citations: [] });
  turns.push({ role: "assistant", text: d.answer, at: now + 1, citations: d.citations.map((c) => c.utterance_id) });
  sessions.set(session, turns);
  const actions = [...(d.actions ?? [])];
  const first = d.citations[0];
  if (first) actions.push({ type: "seek", meeting_id: first.meeting_id, t: first.t_start });
  return {
    answer: d.answer,
    citations: d.citations,
    actions,
    tool_trace: d.tools,
    cypher: d.cypher,
    model: DEMO_MODEL,
    provider: "demo",
    session_id: session,
    timings: { retrieval_ms: 180 + Math.round(Math.random() * 60), llm_ms: 920 + Math.round(Math.random() * 400), total_ms: Math.round(performance.now() - started) + 1240 },
    transcript,
    transcript_provider: transcript ? "demo" : null,
  };
}

function abortable<T>(value: T, ms: number, signal?: AbortSignal): Promise<T> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(new DOMException("Aborted", "AbortError"));
    const t = window.setTimeout(() => resolve(value), ms);
    signal?.addEventListener("abort", () => {
      window.clearTimeout(t);
      reject(new DOMException("Aborted", "AbortError"));
    });
  });
}

// ---- The demo API --------------------------------------------------------------------------------

export const demoApi: Api = {
  health: () =>
    wait<Health>({
      ok: true,
      brand,
      falkordb: { ok: true, version: "4.18.3", graph: "on_record_demo" },
      llm: { provider: "demo", model: DEMO_MODEL, audio: true },
      question_audio: "",
      embedder: { name: "embeddinggemma-300m", dim: 768 },
      asr: { name: "faster-whisper small" },
    }),
  stats: () => wait(stats()),
  meetings: () => wait([...db.meetings].sort((a, b) => b.started_at - a.started_at)),
  createMeeting: () => Promise.reject(new ApiError(503, NEEDS_SERVER)),
  meeting: (id) => {
    try {
      const { meeting, speakers, utterances, decisions, action_items, topics } = detail(id);
      return wait<MeetingDetail>({ meeting, speakers, utterances, decisions, action_items, topics });
    } catch (e) {
      return Promise.reject(e);
    }
  },
  endMeeting: (id) => {
    const m = db.meetings.find((x) => x.id === id);
    return m ? wait(m) : Promise.reject(new ApiError(404, "Meeting not found"));
  },
  deleteMeeting: (id) => {
    db.meetings = db.meetings.filter((m) => m.id !== id);
    delete db.details[id];
    return wait({ deleted: true });
  },
  utterancesAfter: (id, afterSeq) => {
    const d = db.details[id];
    return wait(d ? d.utterances.filter((u) => u.seq > afterSeq) : []);
  },
  uploadMeeting: () => Promise.reject(new ApiError(503, NEEDS_SERVER)),
  audioUrl: (id) => db.details[id]?.audio ?? "",
  nameSpeaker: (meetingId, track, name) => {
    const d = db.details[meetingId];
    const s = d?.speakers.find((x) => x.track === track);
    if (!d || !s) return Promise.reject(new ApiError(404, "Speaker not found"));
    s.name = name;
    d.utterances.forEach((u) => {
      if (u.speaker === track) u.speaker_name = name;
    });
    return wait<Speaker>(s);
  },
  actionItems: (q = {}) =>
    wait(
      allItems()
        .filter((a) => (!q.status || a.status === q.status) && (!q.owner || a.owner === q.owner) && (!q.meeting_id || a.meeting_id === q.meeting_id))
        .sort((a, b) => b.created_at - a.created_at),
    ),
  setActionItem: (id, status) => {
    const a = allItems().find((x) => x.id === id);
    if (!a) return Promise.reject(new ApiError(404, "Action item not found"));
    a.status = status;
    a.done_at = status === "done" ? Date.now() : null;
    return wait<ActionItem>(a, 90);
  },
  decisions: (meetingId) => wait<Decision[]>(allDecisions().filter((d) => !meetingId || d.meeting_id === meetingId)),
  people: () => wait<Person[]>(db.people),
  whoKnows: (topic) => {
    const groups = new Map<string, WhoKnows>();
    for (const h of searchHits(topic, undefined, 30)) {
      const name = h.speaker_name ?? h.speaker;
      const key = `${name}|${h.meeting_id}`;
      const g = groups.get(key);
      if (g) g.hits += 1;
      else {
        const sample = allUtterances().find((u) => u.id === h.utterance_id)!;
        groups.set(key, { name, person_id: db.people.find((p) => p.name === name)?.id ?? null, meeting_id: h.meeting_id, hits: 1, sample });
      }
    }
    return wait([...groups.values()].sort((a, b) => b.hits - a.hits));
  },
  graph: (q = {}) => wait(subgraph(q), 220),
  search: (q, meetingId) => wait(searchHits(q, meetingId)),
  ask: (session_id, question, meeting_id, signal) => abortable(respond(session_id, question, meeting_id), 900 + Math.random() * 500, signal),
  askVoice: () =>
    Promise.reject(new ApiError(503, "Spoken questions need Gemma 4 on the API server. In this preview, type the question instead.")),
  session: (id) => wait(sessions.get(id) ?? []),
};
