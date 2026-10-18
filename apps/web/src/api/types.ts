// Mirrors apps/api/wsw_brain/contracts.py and the dicts GraphStore returns (graph/store.py). Keep in sync.
// docs/ARCHITECTURE.md describes the graph schema and which time fields are seconds or epoch milliseconds.

export type MeetingStatus = "live" | "ended";
export type MeetingSource = "mic" | "upload" | "demo";

export interface MeetingSummary {
  id: string;
  title: string;
  status: MeetingStatus;
  source: MeetingSource;
  started_at: number; // epoch ms
  ended_at: number | null; // epoch ms
  duration_s: number; // seconds
  utterance_count: number;
  speaker_count: number;
  has_audio: boolean;
  summary: string | null;
}

export interface Speaker {
  track: string; // "S1"
  label: string; // "Speaker 1"
  name: string | null;
  person_id: string | null;
  color_idx: number;
  utterance_count: number;
  talk_time_s: number;
}

export interface Utterance {
  id: string;
  meeting_id: string;
  seq: number;
  speaker: string; // track
  speaker_name: string | null;
  t_start: number; // seconds from meeting start
  t_end: number; // seconds from meeting start
  text: string;
  confidence: number; // 0..1: how sure the listener is about who spoke, not transcription confidence
}

export interface Decision {
  id: string;
  meeting_id: string;
  text: string;
  status: "active" | "superseded";
  made_at: number; // seconds from meeting start (not epoch time): when the earliest cited line was said
  proposed_by: string | null; // display name or label ("Priya", "Speaker 2"), not a track
  evidence: string[];
  superseded_by: string | null;
  supersedes: string | null;
}

export interface ActionItem {
  id: string;
  meeting_id: string;
  meeting_title: string;
  text: string;
  owner: string | null; // display name or label, like Decision.proposed_by
  owner_track: string | null; // "S2", when the owner is one of the meeting's speakers
  due: string | null;
  status: "open" | "done";
  created_at: number; // epoch ms
  done_at: number | null; // epoch ms
  evidence: string[];
}

export interface Topic {
  id: string;
  name: string;
  mentions: number;
}

export interface MeetingDetail {
  meeting: MeetingSummary;
  speakers: Speaker[];
  utterances: Utterance[];
  decisions: Decision[];
  action_items: ActionItem[];
  topics: Topic[];
}

export interface Hit {
  utterance_id: string;
  meeting_id: string;
  meeting_title: string;
  speaker: string;
  speaker_name: string | null;
  t_start: number; // seconds from meeting start
  t_end: number; // seconds from meeting start
  text: string;
  score: number;
  via: "fulltext" | "vector" | "graph" | "recent";
}

export interface GraphNode {
  id: string;
  label: string; // display text
  kind: "Meeting" | "Speaker" | "Person" | "Utterance" | "Decision" | "ActionItem" | "Topic" | "Entity" | string;
  [k: string]: unknown;
}
export interface GraphLink {
  source: string;
  target: string;
  type: string;
}
export interface Subgraph {
  nodes: GraphNode[];
  links: GraphLink[];
}

export type ClientAction =
  | { type: "seek"; meeting_id: string; t: number } // t: seconds from meeting start
  | { type: "open_meeting"; meeting_id: string }
  | { type: "refresh"; what: "action_items" | "decisions" | "meeting" }
  | { type: "draft"; title: string; body: string };

export interface AskResult {
  answer: string;
  citations: Hit[];
  actions: ClientAction[];
  tool_trace: { tool: string; args: Record<string, unknown>; result_count: number; ms: number }[];
  cypher: string[];
  model: string;
  provider: string;
  session_id: string;
  timings: Record<string, number>; // ms: retrieve, llm, total
  transcript: string | null;
  transcript_provider: string | null;
}

export interface Health {
  ok: boolean;
  brand: Brand;
  falkordb: { ok: boolean; version: string | null; graph: string };
  llm: { provider: string; model: string; audio: boolean };
  question_audio: string;
  embedder: { name: string; dim: number };
  asr: { name: string };
}

export interface Brand {
  name: string;
  short: string;
  tagline: string;
  event: string;
  track: string;
  problem_statement: string;
}

export interface Person {
  id: string;
  name: string;
  meetings: number;
  utterances: number;
  talk_time_s: number;
  open_items: number;
}

export interface WhoKnows {
  name: string;
  person_id: string | null;
  meeting_id: string;
  hits: number;
  sample: Utterance;
}

export type Stats = Record<string, number>;

export interface BusEvent<T = unknown> {
  id: number;
  type:
    | "meeting.started"
    | "meeting.ended"
    | "utterance.created"
    | "speaker.merged"
    | "speaker.named"
    | "insight.created"
    | "action.updated"
    | "graph.write"
    | "listener.status";
  meeting_id: string | null;
  ts: number; // epoch SECONDS (float), unlike the epoch-ms fields elsewhere
  data: T;
}

export interface Turn {
  role: "user" | "assistant";
  text: string;
  at: number; // epoch ms
  citations: string[];
}
