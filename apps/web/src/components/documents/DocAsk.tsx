// Ask the documents: an answer from Gemma 4 with page citations, optionally translated by Sarvam Mayura and read aloud
// by Sarvam Bulbul.
import { useCallback, useEffect, useId, useMemo, useRef, useState, type KeyboardEvent, type MouseEvent } from "react";
import { Link } from "react-router-dom";
import { CircleNotchIcon, SpeakerHighIcon, StopIcon } from "@phosphor-icons/react";
import {
  documents,
  documentsErrorText,
  languageName,
  LANGUAGES,
  modelName,
  modelVia,
  pagesLabel,
  SPEAKABLE,
  type DocAnswer,
  type DocHit,
  type DocumentSummary,
  type MeetingHit,
} from "../../api/documents";
import { timecode } from "../../lib/format";
import { meetingPath, useJump } from "../ask/useJump";
import { citedRefs, type CiteRef } from "./citations";
import RichText from "./RichText";

const VIA: Record<string, string> = { fulltext: "Full-text match", vector: "Meaning match (EmbeddingGemma)" };
const FLASH_MS = 1800;
const EXAMPLES = ["What does the Starter plan cost?", "When does the usage meter warn on Starter?", "What is the annual discount?"];

function ms(v: number | undefined): string {
  if (typeof v !== "number" || !Number.isFinite(v)) return "";
  return v >= 1000 ? `${(v / 1000).toFixed(1)} s` : `${Math.round(v)} ms`;
}

function pagesLong(h: DocHit): string {
  return h.page_end && h.page_end !== h.page_start ? `pages ${h.page_start} to ${h.page_end}` : `page ${h.page_start}`;
}

interface Asked {
  question: string;
  scopeTitle: string;
  answer: DocAnswer;
}

type Speech = { key: string; phase: "loading" | "playing" } | null;

/** One answer read aloud at a time; the object URL is released when playback ends or stops. */
function useSpeech() {
  const [speech, setSpeech] = useState<Speech>(null);
  const [speechError, setSpeechError] = useState<string | null>(null);
  const audio = useRef<HTMLAudioElement | null>(null);
  const url = useRef<string | null>(null);
  const abort = useRef<AbortController | null>(null);

  const stop = useCallback(() => {
    abort.current?.abort();
    abort.current = null;
    if (audio.current) {
      audio.current.onended = null;
      audio.current.onerror = null;
      audio.current.pause();
      audio.current = null;
    }
    if (url.current) {
      URL.revokeObjectURL(url.current);
      url.current = null;
    }
    setSpeech(null);
  }, []);

  useEffect(() => stop, [stop]);

  const play = useCallback(
    async (key: string, text: string, language: string) => {
      stop();
      setSpeechError(null);
      const ctrl = new AbortController();
      abort.current = ctrl;
      setSpeech({ key, phase: "loading" });
      try {
        const { blob } = await documents.speak({ text, language }, ctrl.signal);
        if (ctrl.signal.aborted) return;
        const src = URL.createObjectURL(blob);
        url.current = src;
        const el = new Audio(src);
        audio.current = el;
        el.onended = stop;
        el.onerror = () => {
          setSpeechError("The audio couldn't be played.");
          stop();
        };
        await el.play();
        if (audio.current === el) setSpeech({ key, phase: "playing" });
      } catch (e) {
        if (ctrl.signal.aborted || (e instanceof DOMException && e.name === "AbortError")) return;
        setSpeechError(`Couldn't read it aloud. ${documentsErrorText(e)}`);
        stop();
      }
    },
    [stop],
  );

  return { speech, speechError, play, stop };
}

interface ListenProps {
  id: string;
  text: string;
  language: string;
  speech: Speech;
  play: (key: string, text: string, language: string) => void;
  stop: () => void;
}

function Listen({ id, text, language, speech, play, stop }: ListenProps) {
  if (!SPEAKABLE.has(language)) return null;
  const mine = speech?.key === id ? speech.phase : null;
  const name = languageName(language);
  return (
    <span className="dx-listen">
      {mine ? (
        <button type="button" className="btn btn--ghost mp-mini" onClick={stop} aria-label={mine === "loading" ? "Cancel reading aloud" : "Stop reading aloud"}>
          {mine === "loading" ? <CircleNotchIcon aria-hidden="true" className="spin" /> : <StopIcon aria-hidden="true" weight="fill" />}
          {mine === "loading" ? "Preparing audio…" : "Stop"}
        </button>
      ) : (
        <button type="button" className="btn btn--ghost mp-mini" onClick={() => play(id, text, language)} aria-label={`Listen in ${name}`}>
          <SpeakerHighIcon aria-hidden="true" />
          Listen
        </button>
      )}
      <span className="dx-listen__by">Spoken by Sarvam Bulbul</span>
    </span>
  );
}

interface Props {
  docs: DocumentSummary[];
  /** "" for all documents, else a document id */
  scope: string;
  onScope: (scope: string) => void;
}

export default function DocAsk({ docs, scope, onScope }: Props) {
  const uid = useId();
  const [question, setQuestion] = useState("");
  const [replyIn, setReplyIn] = useState("en-IN");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [asked, setAsked] = useState<Asked | null>(null);
  const [withMeetings, setWithMeetings] = useState(true);
  const [flash, setFlash] = useState<string | null>(null);
  const jump = useJump();
  const citeRefs = useRef(new Map<string, HTMLLIElement>());
  const flashTimer = useRef<number | null>(null);
  const { speech, speechError, play, stop } = useSpeech();

  useEffect(
    () => () => {
      if (flashTimer.current) window.clearTimeout(flashTimer.current);
    },
    [],
  );

  const scopeDoc = docs.find((d) => d.id === scope) ?? null;

  const submit = async (text?: string) => {
    const q = (text ?? question).trim();
    if (!q || busy) return;
    stop();
    setBusy(true);
    setError(null);
    try {
      const answer = await documents.ask({
        question: q,
        doc_id: scopeDoc?.id ?? null,
        language: replyIn === "en-IN" ? undefined : replyIn,
        include_meetings: withMeetings,
      });
      setAsked({ question: q, scopeTitle: scopeDoc?.title ?? "All documents", answer });
    } catch (e) {
      setError(documentsErrorText(e));
    } finally {
      setBusy(false);
    }
  };

  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      void submit();
    }
  };

  const answer = asked?.answer ?? null;
  const byId = useMemo(() => {
    const m = new Map<string, DocHit>();
    for (const h of [...(answer?.hits ?? []), ...(answer?.citations ?? [])]) m.set(h.id, h);
    return m;
  }, [answer]);
  const byUtterance = useMemo(() => {
    const m = new Map<string, MeetingHit>();
    for (const h of [...(answer?.meeting_hits ?? []), ...(answer?.meeting_citations ?? [])]) m.set(h.utterance_id, h);
    return m;
  }, [answer]);

  // Cited passages and meeting lines in the order the answer first cites them, then any other citations returned.
  const { cited, citedLines } = useMemo(() => {
    if (!answer) return { cited: [] as DocHit[], citedLines: [] as MeetingHit[] };
    const refs: CiteRef[] = [
      ...citedRefs(answer.answer),
      ...answer.citations.map((c) => ({ kind: "d" as const, id: c.id })),
      ...(answer.meeting_citations ?? []).map((c) => ({ kind: "u" as const, id: c.utterance_id })),
    ];
    const seen = new Set<string>();
    const docs: DocHit[] = [];
    const lines: MeetingHit[] = [];
    for (const r of refs) {
      const key = `${r.kind}:${r.id}`;
      if (seen.has(key)) continue;
      seen.add(key);
      if (r.kind === "d") {
        const h = byId.get(r.id);
        if (h) docs.push(h);
      } else {
        const h = byUtterance.get(r.id);
        if (h) lines.push(h);
      }
    }
    return { cited: docs, citedLines: lines };
  }, [answer, byId, byUtterance]);
  const anyCited = cited.length + citedLines.length > 0;
  const shown = anyCited ? cited : (answer?.hits ?? []);
  const multiDoc = new Set(shown.map((h) => h.doc_id)).size > 1;
  // Gemma 4 is asked to say when a newer meeting changed what a document says; flag answers that lean on both.
  const changedByMeetings = cited.length > 0 && citedLines.length > 0;

  const focusCite = (key: string) => {
    const el = citeRefs.current.get(key);
    if (!el) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    el.scrollIntoView({ block: "nearest", behavior: reduce ? "auto" : "smooth" });
    el.focus({ preventScroll: true });
    setFlash(key);
    if (flashTimer.current) window.clearTimeout(flashTimer.current);
    flashTimer.current = window.setTimeout(() => setFlash(null), FLASH_MS);
  };

  const openLine = (e: MouseEvent<HTMLAnchorElement>, h: MeetingHit) => {
    // a plain click seeks the meeting player to the line; modified clicks open the link as usual
    if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    jump({ meeting_id: h.meeting_id, t: h.t_start, utterance_id: h.utterance_id });
  };

  const lineHref = (h: MeetingHit) =>
    `${meetingPath(h.meeting_id)}?${new URLSearchParams({ t: String(Math.round(h.t_start * 100) / 100), u: h.utterance_id })}`;

  const chip = (ref: CiteRef, key: string) => {
    if (ref.kind === "u") {
      const h = byUtterance.get(ref.id);
      if (!h) return null;
      const who = h.speaker_name || "Speaker";
      return (
        <Link
          key={key}
          to={lineHref(h)}
          className="dx-chip dx-chip--meeting"
          onClick={(e) => openLine(e, h)}
          title={h.text}
          aria-label={`${who} in ${h.meeting_title} at ${timecode(h.t_start)}. Opens the meeting`}
        >
          {who} · {h.meeting_title} · {timecode(h.t_start)}
        </Link>
      );
    }
    const h = byId.get(ref.id);
    if (!h) return null;
    return (
      <button
        key={key}
        type="button"
        className="dx-chip"
        onClick={() => focusCite(`d:${ref.id}`)}
        title={`${h.doc_title}${h.heading ? ` · ${h.heading}` : ""}`}
        aria-label={`Source: ${h.doc_title}, ${pagesLong(h)}`}
      >
        {pagesLabel(h.page_start, h.page_end)}
      </button>
    );
  };

  // Mayura flattens list lines into one paragraph, leaving the bullets inline as " * "; drop them.
  const translated = answer?.translated_answer ? answer.translated_answer.replace(/(^|\s)\*\s+/g, "$1") : null;
  const answerLang = answer?.answer_language ?? replyIn;
  const timingBits = answer
    ? [
        answer.timings.retrieval_ms !== undefined ? `Retrieval ${ms(answer.timings.retrieval_ms)}` : "",
        answer.timings.model_ms !== undefined ? `${modelName(answer.model) || "Model"} ${ms(answer.timings.model_ms)}` : "",
        answer.timings.translate_ms !== undefined ? `Translation ${ms(answer.timings.translate_ms)}` : "",
      ].filter(Boolean)
    : [];
  const answeredBy = answer ? modelVia(answer.model, answer.provider) : "";

  const english = answer ? (
    <>
      <RichText className="dx-prose dx-answer__text" text={answer.answer} renderCite={chip} />
      <Listen id="en" text={answer.answer} language="en-IN" speech={speech} play={play} stop={stop} />
    </>
  ) : null;

  return (
    <section className="panel dx-ask" aria-labelledby={`${uid}-h`}>
      <div className="dx-sec-head">
        <h2 id={`${uid}-h`}>Ask your documents</h2>
        <p className="dx-hint">Answers cite the pages, and the meeting moments, they come from.</p>
      </div>

      <form
        className="dx-ask__form"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <label className="visually-hidden" htmlFor={`${uid}-q`}>
          Question
        </label>
        <textarea
          id={`${uid}-q`}
          className="field dx-ask__q"
          rows={2}
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={onKey}
          placeholder={docs.length ? "What are the deadlines? Who owns the open tasks?" : "Add a document first, then ask about it"}
          disabled={!docs.length}
        />
        <div className="dx-ask__row">
          <label className="dx-field dx-field--inline">
            <span className="dx-label">Search in</span>
            <select className="field dx-select" value={scopeDoc ? scope : ""} onChange={(e) => onScope(e.target.value)} disabled={!docs.length}>
              <option value="">All documents</option>
              {docs.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.title}
                </option>
              ))}
            </select>
          </label>
          <label className="dx-field dx-field--inline">
            <span className="dx-label">Reply in</span>
            <select className="field dx-select" value={replyIn} onChange={(e) => setReplyIn(e.target.value)} disabled={!docs.length}>
              {LANGUAGES.map((l) => (
                <option key={l.code} value={l.code}>
                  {l.name}
                </option>
              ))}
            </select>
          </label>
          <label className="dx-check">
            <input type="checkbox" className="check" checked={withMeetings} onChange={(e) => setWithMeetings(e.target.checked)} />
            <span>Also check meetings</span>
          </label>
          <button type="submit" className="btn btn--primary dx-ask__go" disabled={!question.trim() || busy || !docs.length}>
            {busy ? <CircleNotchIcon aria-hidden="true" className="spin" /> : null}
            {busy ? "Asking…" : "Ask"}
          </button>
        </div>
      </form>

      {docs.length ? (
        <div className="dx-examples" role="group" aria-label="Example questions">
          {EXAMPLES.map((q) => (
            <button
              key={q}
              type="button"
              className="dx-example"
              disabled={busy}
              onClick={() => {
                setQuestion(q);
                void submit(q);
              }}
            >
              {q}
            </button>
          ))}
        </div>
      ) : null}

      <p className="visually-hidden" aria-live="polite">
        {busy ? "Asking…" : asked ? `Answer ready${asked.answer.translated_answer ? `, translated to ${languageName(asked.answer.answer_language)}` : ""}.` : ""}
      </p>
      <div aria-busy={busy}>
        {busy ? (
          <p className="dx-note">
            Searching {scopeDoc ? `“${scopeDoc.title}”` : "all documents"}
            {withMeetings ? " and your meetings" : ""}, then asking {replyIn === "en-IN" ? "Gemma 4" : `Gemma 4 and translating to ${languageName(replyIn)}`}…
          </p>
        ) : null}

        {error ? (
          <div className="mp-alert dx-alert" role="alert">
            <p>That question didn't go through. {error}</p>
            <button type="button" className="btn mp-mini" onClick={() => void submit()}>
              Try again
            </button>
          </div>
        ) : null}

        {asked && answer && !busy ? (
          <article className="dx-answer" aria-label="Answer">
            <p className="dx-answer__q">
              <span className="eyebrow">{asked.scopeTitle}</span>
              <span className="dx-answer__qtext">{asked.question}</span>
            </p>

            {changedByMeetings ? (
              <p className="dx-changed">
                <span className="dx-changed__tag">Meetings changed this</span>
                This answer draws on both the documents and your meetings; where a newer meeting changed what a document
                says, Gemma 4 points it out.
              </p>
            ) : null}

            {translated ? (
              <div className="dx-answer__block" lang={answerLang === "od-IN" ? "or-IN" : answerLang}>
                <p className="dx-prov dx-prov--top">Translated to {languageName(answerLang)} by {answer.translated_by ?? "Sarvam Mayura"}</p>
                <RichText className="dx-prose dx-answer__text dx-answer__text--lead" text={translated} />
                <Listen id="tr" text={translated} language={answerLang} speech={speech} play={play} stop={stop} />
              </div>
            ) : null}

            {answer.translation_error ? (
              <div className="mp-alert dx-alert" role="status">
                <p>
                  Couldn't translate to {languageName(answerLang)}: {answer.translation_error} Showing the English answer.
                </p>
              </div>
            ) : null}

            {translated ? (
              <details className="dx-orig" open>
                <summary>Original English answer</summary>
                <div className="dx-answer__block">{english}</div>
              </details>
            ) : (
              <div className="dx-answer__block">{english}</div>
            )}

            {speechError ? <p className="dx-note dx-note--warn">{speechError}</p> : null}

            <p className="dx-prov">
              {answeredBy ? `Answered by ${answeredBy}` : "No model answered; these are the closest passages"}
              {timingBits.length ? <span className="tc"> · {timingBits.join(" · ")}</span> : null}
            </p>

            {shown.length ? (
              <section className="dx-cites" aria-label={anyCited ? "Cited passages" : "Closest passages"}>
                <h3 className="dx-cites__h">
                  {anyCited ? (cited.length === 1 ? "1 cited passage" : `${cited.length} cited passages`) : "Closest passages"}
                </h3>
                <ol className="dx-cites__list">
                  {shown.map((h) => (
                    <li
                      key={h.id}
                      ref={(el) => {
                        if (el) citeRefs.current.set(`d:${h.id}`, el);
                        else citeRefs.current.delete(`d:${h.id}`);
                      }}
                      tabIndex={-1}
                      className={`dx-cite${flash === `d:${h.id}` ? " is-flash" : ""}`}
                    >
                      <p className="dx-cite__meta">
                        <span className="dx-cite__pages">{pagesLabel(h.page_start, h.page_end)}</span>
                        {multiDoc || !scopeDoc ? <span className="dx-cite__doc">{h.doc_title}</span> : null}
                        {h.heading ? <span className="dx-cite__heading">{h.heading}</span> : null}
                        <span className="dx-cite__via">{VIA[h.via] ?? h.via}</span>
                      </p>
                      <p className="dx-cite__text">{h.text}</p>
                    </li>
                  ))}
                </ol>
              </section>
            ) : null}

            {citedLines.length ? (
              <section className="dx-cites" aria-label="Cited meeting lines">
                <h3 className="dx-cites__h">
                  {citedLines.length === 1 ? "1 cited meeting line" : `${citedLines.length} cited meeting lines`}
                </h3>
                <ol className="dx-cites__list">
                  {citedLines.map((h) => (
                    <li key={h.utterance_id} className="dx-cite dx-cite--meeting">
                      <p className="dx-cite__meta">
                        <span className="dx-cite__who">{h.speaker_name || "Speaker"}</span>
                        <Link to={lineHref(h)} className="dx-cite__doc" onClick={(e) => openLine(e, h)}>
                          {h.meeting_title}
                        </Link>
                        {h.meeting_date ? <span>{h.meeting_date}</span> : null}
                        <span className="tc">{timecode(h.t_start)}</span>
                      </p>
                      <blockquote className="quote dx-cite__quote">{h.text}</blockquote>
                    </li>
                  ))}
                </ol>
              </section>
            ) : null}
          </article>
        ) : null}
      </div>
    </section>
  );
}
