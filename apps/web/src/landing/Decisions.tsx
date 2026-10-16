import { ArrowRight, CircleCheck, Play } from "lucide-react";
import type { Decision } from "../api/types";
import { timecode, when } from "../lib/format";
import { playLine, type Deck } from "./deck";
import { SIDES, type Side } from "./sides";

const allUtterances = new Map(SIDES.flatMap((s) => s.utterances.map((u) => [u.id, { u, side: s }] as const)));

function Evidence({ deck, id }: { deck: Deck; id: string }) {
  const hit = allUtterances.get(id);
  if (!hit) return null;
  const { u, side } = hit;
  return (
    <blockquote className={`ev spk spk-${side.colours.get(u.speaker) ?? 7}`}>
      <p className="ev-text">{u.text}</p>
      <footer className="ev-foot">
        <button type="button" className="ev-play" onClick={() => playLine(deck, side, u)} aria-label={`Play ${u.speaker_name} at ${timecode(u.t_start)} in ${side.title}`}>
          <Play aria-hidden="true" />
        </button>
        <span className="ev-who">{u.speaker_name}</span>
        <span className="tc ev-at">{timecode(u.t_start)}</span>
      </footer>
    </blockquote>
  );
}

function DecisionCard({ deck, d, side, delay }: { deck: Deck; d: Decision; side: Side; delay: number }) {
  const replaced = d.status === "superseded";
  return (
    <article className={`dec${replaced ? " dec--replaced" : ""}`} data-reveal="frame" style={{ ["--d" as string]: delay }}>
      <header className="dec-head">
        <span className="dec-meeting">
          {side.title} <span className="dec-date">{when(side.startedAt)}</span>
        </span>
        <span className={`dec-status${replaced ? "" : " is-active"}`}>{replaced ? "Replaced" : "Standing"}</span>
      </header>
      <p className="dec-text">{d.text}</p>
      <p className="dec-by">
        Proposed by {d.proposed_by} <span className="tc">at {timecode(d.made_at)}</span>
      </p>
      <Evidence deck={deck} id={d.evidence[d.evidence.length - 1]} />
    </article>
  );
}

export default function Decisions({ deck }: { deck: Deck }) {
  const [a, b] = SIDES;
  const newer = b.decisions.find((d) => d.supersedes);
  const older = newer ? a.decisions.find((d) => d.id === newer.supersedes) : undefined;
  const items = [...a.actionItems, ...b.actionItems].filter((x) => x.status === "open").slice(0, 6);

  return (
    <section className="l-section decisions" aria-labelledby="decisions-title">
      <div className="l-wrap">
        <div className="l-head">
          <h2 id="decisions-title" className="l-h2" data-reveal>
            Decisions that know when they changed.
          </h2>
          <p className="l-lede" data-reveal style={{ ["--d" as string]: 1 }}>
            Gemma 4 reads along as the meeting happens. It pulls out decisions, owners and due dates, and ties each one to the words that
            justify it. When a later meeting changes a decision, the old one is marked replaced in the graph, not lost.
          </p>
        </div>

        {older && newer && (
          <div className="dec-pair">
            <DecisionCard deck={deck} d={older} side={a} delay={0} />
            <div className="dec-link" aria-hidden="true" data-reveal style={{ ["--d" as string]: 3 }}>
              <span className="dec-link-label">supersedes</span>
              <ArrowRight />
            </div>
            <DecisionCard deck={deck} d={newer} side={b} delay={5} />
          </div>
        )}

        <div className="commit">
          <h3 className="commit-title">Open commitments, by owner</h3>
          <ul className="commit-list">
            {items.map((x, i) => {
              const side = SIDES.find((s) => s.id === x.meeting_id)!;
              const track = x.owner_track ?? "";
              return (
                <li key={x.id} className={`commit-row spk spk-${side.colours.get(track) ?? 7}`} data-reveal style={{ ["--d" as string]: i }}>
                  <CircleCheck aria-hidden="true" className="commit-icon" />
                  <span className="commit-owner">{x.owner}</span>
                  <span className="commit-text">{x.text}</span>
                  <span className="commit-due">{x.due ? `Due ${x.due}` : "No date"}</span>
                </li>
              );
            })}
          </ul>
        </div>
      </div>
    </section>
  );
}
