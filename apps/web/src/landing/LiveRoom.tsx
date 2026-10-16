import { useEffect, useMemo, useRef, useState } from "react";
import { Database } from "lucide-react";
import type { ActionItem, Topic, Utterance } from "../api/types";
import InsightsRail from "../components/meeting/InsightsRail";
import SpeakerLanes from "../components/meeting/SpeakerLanes";
import Transcript from "../components/meeting/Transcript";
import { duration, speakerName } from "../lib/format";
import { useDeckState, type Deck } from "./deck";
import { speakingAt } from "./sides";

// A line lands in the graph a moment after its speaker pauses (about 2 s in the measured build).
const LANDS_AFTER_S = 2;
const FRESH_MS = 2600;

/** The app's own meeting room components, replaying the side on the record as if it were live. */
export default function LiveRoom({ deck }: { deck: Deck }) {
  const { side: sideIdx, rate, sound } = useDeckState(deck);
  const frameRef = useRef<HTMLDivElement>(null);
  const cued = useRef(false);
  const side = deck.current;
  const [count, setCount] = useState(0);
  const [speaking, setSpeaking] = useState<string | null>(null);
  const [fresh, setFresh] = useState<ReadonlySet<string>>(new Set());
  const lastCount = useRef(0);

  useEffect(() => {
    lastCount.current = 0;
    let raf = 0;
    const tick = () => {
      const t = deck.time();
      let n = 0;
      while (n < side.utterances.length && side.utterances[n].t_end + LANDS_AFTER_S <= t) n++;
      if (n !== lastCount.current) {
        const added = n > lastCount.current ? side.utterances.slice(lastCount.current, n).map((u) => u.id) : [];
        lastCount.current = n;
        setCount(n);
        if (added.length) {
          setFresh(new Set(added));
          window.setTimeout(() => setFresh((f) => (f.has(added[0]) ? new Set() : f)), FRESH_MS);
        }
      }
      const now = speakingAt(side, t);
      setSpeaking((prev) => (prev === (now?.id ?? null) ? prev : (now?.id ?? null)));
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [deck, side, sideIdx]);

  // In view and silent: cue the meeting to just before its first decision and replay at 2x, so lines and
  // Gemma's extractions land while you watch. Out of view, or with the sound on, the clock runs at 1x.
  useEffect(() => {
    const el = frameRef.current;
    if (!el) return;
    const io = new IntersectionObserver(
      ([e]) => {
        if (!e.isIntersecting || deck.state.sound) {
          deck.setRate(1);
          return;
        }
        const first = Math.min(...deck.current.decisions.map((d) => d.made_at));
        if (!cued.current && Number.isFinite(first) && deck.time() < first - 45) deck.seek(Math.max(0, first - 40));
        cued.current = true;
        deck.setRate(2);
      },
      { threshold: 0.35 },
    );
    io.observe(el);
    return () => {
      io.disconnect();
      deck.setRate(1);
    };
  }, [deck]);

  const utterances = useMemo(() => side.utterances.slice(0, count), [side, count]);
  const landed = useMemo(() => new Set(utterances.map((u) => u.id)), [utterances]);
  const byId = useMemo(() => new Map<string, Utterance>(side.utterances.map((u) => [u.id, u])), [side]);
  const names = useMemo(() => new Map(side.speakers.map((s) => [s.track, speakerName(s)])), [side]);
  const nameOf = (track: string) => names.get(track) ?? track;

  // Gemma's extractions appear once the words that justify them have landed.
  const decisions = useMemo(() => side.decisions.filter((d) => d.evidence.every((id) => landed.has(id))), [side, landed]);
  const actionItems = useMemo<ActionItem[]>(() => side.actionItems.filter((a) => a.evidence.every((id) => landed.has(id))), [side, landed]);
  const topics = useMemo<Topic[]>(() => {
    const counts = new Map<string, number>();
    for (const [uid, tid] of side.topicLinks) if (landed.has(uid)) counts.set(tid, (counts.get(tid) ?? 0) + 1);
    return side.topics.filter((t) => counts.has(t.id)).map((t) => ({ ...t, mentions: counts.get(t.id)! }));
  }, [side, landed]);

  const seek = (u: Utterance) => deck.seek(u.t_start + 0.05);

  return (
    <div ref={frameRef} className="room-frame" data-reveal="frame" aria-label={`The meeting room, replaying ${side.title}`}>
      <div className="room-frame-bar">
        <span className="room-frame-dots" aria-hidden="true">
          <i />
          <i />
          <i />
        </span>
        <span className="room-frame-url">on-record.local/m/{side.id}</span>
      </div>
      <div className="room-frame-body">
        <header className="room-frame-head">
          <div>
            <h3 className="room-frame-title">{side.title}</h3>
            <p className="room-frame-meta">
              <span className="room-frame-live">
                <i className="live-dot" aria-hidden="true" /> Replaying as live{rate !== 1 && !sound ? ` at ${rate}×` : ""}
              </span>
              <span>{duration(side.duration)}</span>
              <span>{side.speakers.length} speakers</span>
            </p>
          </div>
        </header>
        <SpeakerLanes
          speakers={side.speakers}
          utterances={utterances}
          colours={side.colours}
          domain={side.duration}
          readHead={() => deck.time()}
          headMode="live"
          follow={false}
          fresh={fresh}
          activeId={speaking}
          onPick={seek}
          onScrub={(t) => deck.seek(t)}
          onRename={async () => undefined}
          meta={
            <span className="room-frame-writes">
              <Database aria-hidden="true" />
              Written to FalkorDB <b className="tc">{count}</b> utterances
            </span>
          }
          emptyText="Nothing said yet. Each line appears a moment after the speaker finishes."
        />
        <div className="room-frame-split">
          <Transcript
            utterances={utterances}
            colours={side.colours}
            nameOf={nameOf}
            heardId={speaking}
            target={null}
            live
            canPlay
            onSeek={seek}
            emptyText="Nothing said yet. Each line appears a moment after the speaker finishes."
          />
          <InsightsRail
            decisions={decisions}
            actionItems={actionItems}
            topics={topics}
            utterancesById={byId}
            colours={side.colours}
            nameOf={nameOf}
            fresh={fresh}
            live
            onEvidence={seek}
            onToggleAction={async () => undefined}
          />
        </div>
      </div>
    </div>
  );
}
