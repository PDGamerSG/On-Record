// The two bundled demo meetings, read as the two sides of one record. Everything the landing page shows
// (grooves, captions, lanes, decisions) comes from the same fixtures the app's demo mode serves.
import raw from "../api/demo/fixtures.json";
import type { ActionItem, Decision, Speaker, Topic, Utterance } from "../api/types";
import { colourMap } from "../components/meeting/meetingState";

interface Detail {
  meeting: { id: string; title: string; duration_s: number; started_at: number; summary?: string | null };
  speakers: Speaker[];
  utterances: Utterance[];
  decisions: Decision[];
  action_items: ActionItem[];
  topics: Topic[];
  topic_links: [string, string][];
  audio: string;
}

export interface Side {
  id: string;
  letter: "A" | "B";
  title: string;
  duration: number;
  startedAt: number;
  audio: string;
  speakers: Speaker[];
  utterances: Utterance[];
  decisions: Decision[];
  actionItems: ActionItem[];
  topics: Topic[];
  /** [utterance id, topic id] */
  topicLinks: [string, string][];
  /** speaker track -> palette index (0..7) */
  colours: Map<string, number>;
}

const details = (raw as unknown as { details: Record<string, Detail> }).details;

function side(id: string, letter: Side["letter"]): Side {
  const d = details[id];
  return {
    id,
    letter,
    title: d.meeting.title,
    duration: d.meeting.duration_s,
    startedAt: d.meeting.started_at,
    audio: d.audio,
    speakers: d.speakers,
    utterances: [...d.utterances].sort((a, b) => a.t_start - b.t_start),
    decisions: d.decisions,
    actionItems: d.action_items,
    topics: d.topics,
    topicLinks: d.topic_links,
    colours: colourMap(d.speakers),
  };
}

export const SIDES: Side[] = [side("demo-pricing-review", "A"), side("demo-launch-sync", "B")];

/** The line being spoken at t, or the last one that started before t (so pauses keep a caption). */
export function lineAt(s: Side, t: number): Utterance | null {
  let lo = 0;
  let hi = s.utterances.length - 1;
  let found = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (s.utterances[mid].t_start <= t) {
      found = mid;
      lo = mid + 1;
    } else hi = mid - 1;
  }
  return found >= 0 ? s.utterances[found] : null;
}

/** Whoever is speaking exactly at t, or null in a pause. */
export function speakingAt(s: Side, t: number): Utterance | null {
  const u = lineAt(s, t);
  return u && t <= u.t_end ? u : null;
}

export function colourOf(s: Side, track: string): number {
  return s.colours.get(track) ?? 7;
}

/** Hex values of --spk-0..7, read from tokens.css so the canvas and WebGL art match the CSS. */
export function speakerHex(): string[] {
  const css = getComputedStyle(document.documentElement);
  return Array.from({ length: 8 }, (_, i) => css.getPropertyValue(`--spk-${i}`).trim() || "#8ca0b3");
}
