// Upload a document: preview how the splitter cuts it into Sarvam-sized parts, then ingest it and follow the job live.
import { useEffect, useId, useRef, useState, type DragEvent } from "react";
import { CheckCircleIcon, CircleNotchIcon, FileTextIcon, UploadSimpleIcon, WarningCircleIcon } from "@phosphor-icons/react";
import {
  documents,
  documentsErrorText,
  LANGUAGES,
  modelVia,
  pagesLabel,
  type DocStage,
  type DocumentsStatus,
  type Job,
  type SplitPart,
  type SplitPlan,
} from "../../api/documents";
import RichText from "./RichText";

const ACCEPT = ".pdf,.png,.jpg,.jpeg,.zip";
const ACCEPT_RE = /\.(pdf|png|jpe?g|zip)$/i;
const POLL_MS = 1500;
const MAX_POLL_FAILURES = 5;

type PartState = "planned" | "working" | "done" | "failed" | "stopped";
type StepState = "pending" | "active" | "done" | "skipped" | "failed";

const PART_LABEL: Record<PartState, string> = {
  planned: "Ready",
  working: "Digitising",
  done: "Digitised",
  failed: "Failed",
  stopped: "Stopped",
};

const SAMPLE = {
  url: "/samples/kitepost-pricing-policy.pdf",
  filename: "kitepost-pricing-policy.pdf",
  title: "Kitepost pricing policy",
};

function bytes(n: number): string {
  if (n >= 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MB`;
  if (n >= 1024) return `${Math.round(n / 1024)} KB`;
  return `${n} B`;
}

function secs(s: number | undefined): string {
  return typeof s === "number" && Number.isFinite(s) ? `${s.toFixed(1)} s` : "";
}

function partStates(parts: SplitPart[], job: Job | null): Map<number, PartState> {
  const out = new Map<number, PartState>();
  if (!job) {
    for (const p of parts) out.set(p.index, "planned");
    return out;
  }
  const finished = new Set(job.events.filter((e) => e.stage === "digitise" && typeof e.part === "number").map((e) => e.part as number));
  const split = job.events.some((e) => e.stage === "split");
  for (const p of parts) {
    const fromResult = job.result?.parts.find((r) => r.index === p.index);
    if (fromResult) out.set(p.index, /fail/i.test(fromResult.status) ? "failed" : "done");
    else if (finished.has(p.index)) out.set(p.index, "done");
    else if (job.status === "failed") out.set(p.index, "stopped");
    else out.set(p.index, split || job.status === "running" ? "working" : "planned");
  }
  return out;
}

interface Step {
  stage: DocStage;
  label: string;
  detail: string;
  state: StepState;
}

function steps(job: Job, status: DocumentsStatus | null): Step[] {
  const ev = (stage: DocStage) => [...job.events].reverse().find((e) => e.stage === stage);
  const split = ev("split");
  const dig = ev("digitise");
  const chunk = ev("chunk");
  const embed = ev("embed");
  const store = ev("store");
  const summary = ev("summary");
  const visionEvents = job.events.filter((e) => e.stage === "vision");
  const vision = visionEvents[visionEvents.length - 1];
  const parts = split?.parts ?? dig?.parts ?? 0;
  const digDone = !!dig && (dig.done ?? 0) >= (dig.parts ?? parts) && parts > 0;
  const llm = summary?.model ?? job.result?.summary?.model ?? status?.llm.model;
  const provider = job.result?.summary?.provider ?? status?.llm.provider;
  const list: Omit<Step, "state">[] = [
    { stage: "split", label: "Split", detail: split ? `${split.pages} pages into ${split.parts} ${split.parts === 1 ? "part" : "parts"}` : "Cutting into parts" },
    {
      stage: "digitise",
      label: "Digitised by Sarvam Vision",
      detail: dig ? `${dig.done} of ${dig.parts} parts` : parts ? `0 of ${parts} parts, in parallel` : "Parts run in parallel",
    },
    // image uploads only: Gemma 4 also describes the picture, stored as its own passage
    ...(vision
      ? [
          {
            stage: "vision" as const,
            label: "Gemma 4 looked at the image",
            detail: `Described by ${modelVia(vision.model, provider) || "Gemma 4"}${visionEvents.length > 1 ? ` · ${visionEvents.length} images` : ""}`,
          },
        ]
      : []),
    { stage: "chunk", label: "Chunk", detail: chunk ? `${chunk.chunks} passages` : "Passages with page ranges" },
    { stage: "embed", label: "Embed", detail: embed ? `${embed.embedder ?? status?.embedder ?? "EmbeddingGemma"}` : status?.embedder ?? "EmbeddingGemma" },
    { stage: "store", label: "Store", detail: store ? `${store.written ?? chunk?.chunks ?? ""} passages in FalkorDB`.trim() : "FalkorDB graph" },
    { stage: "summary", label: "Summary", detail: `By ${modelVia(llm, provider) || "the language model"}` },
  ];
  const done: Record<DocStage, boolean> = {
    split: !!split,
    digitise: digDone,
    vision: !!vision,
    chunk: !!chunk,
    embed: !!embed,
    store: !!store,
    summary: !!summary,
  };
  let activeGiven = false;
  return list.map((s) => {
    let state: StepState;
    if (done[s.stage]) state = "done";
    else if (job.status === "done") state = "skipped";
    else if (!activeGiven) {
      state = job.status === "failed" ? "failed" : "active";
      activeGiven = true;
    } else state = "pending";
    return { ...s, state };
  });
}

function progressSentence(job: Job, list: Step[]): string {
  if (job.status === "done") return `Ingested ${job.result?.title ?? job.filename}${job.result ? ` in ${secs(job.result.total_s)}` : ""}.`;
  if (job.status === "failed") return `Ingest failed. ${job.error ?? ""}`;
  const active = list.find((s) => s.state === "active");
  return active ? `${active.label}: ${active.detail}.` : "Working…";
}

interface Props {
  status: DocumentsStatus | null;
  /** called once the job finishes, with the new document's id */
  onIngested: (docId: string) => void;
  onOpen: (docId: string) => void;
}

export default function DocUpload({ status, onIngested, onOpen }: Props) {
  const uid = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [plan, setPlan] = useState<SplitPlan | null>(null);
  const [splitting, setSplitting] = useState(false);
  const [fileError, setFileError] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [language, setLanguage] = useState("en-IN");
  const [uploading, setUploading] = useState(false);
  const [job, setJob] = useState<Job | null>(null);
  const [jobError, setJobError] = useState<string | null>(null);
  const [pollFailures, setPollFailures] = useState(0);
  const [dragging, setDragging] = useState(false);
  const [loadingSample, setLoadingSample] = useState(false);
  const pickToken = useRef(0);
  const onIngestedRef = useRef(onIngested);
  useEffect(() => {
    onIngestedRef.current = onIngested;
  }, [onIngested]);

  const running = uploading || job?.status === "running";

  const choose = async (f: File | null | undefined) => {
    if (!f || running) return;
    const token = ++pickToken.current;
    setJob(null);
    setJobError(null);
    setPlan(null);
    setFile(f);
    setTitle("");
    if (!ACCEPT_RE.test(f.name)) {
      setFileError("Choose a PDF, PNG, JPEG, or a ZIP of page images.");
      return;
    }
    if (status && f.size > status.max_mb * 1024 * 1024) {
      setFileError(`This file is ${bytes(f.size)}; the limit is ${status.max_mb} MB.`);
      return;
    }
    setFileError(null);
    setSplitting(true);
    try {
      const p = await documents.split(f);
      if (token === pickToken.current) setPlan(p);
    } catch (e) {
      if (token === pickToken.current) setFileError(documentsErrorText(e));
    } finally {
      if (token === pickToken.current) setSplitting(false);
    }
  };

  // A bundled 12-page policy: long enough to be split into two parts, and written to disagree with the demo meetings.
  const trySample = async () => {
    if (running || loadingSample) return;
    setLoadingSample(true);
    try {
      const res = await fetch(SAMPLE.url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const blob = await res.blob();
      await choose(new File([blob], SAMPLE.filename, { type: "application/pdf" }));
      setTitle(SAMPLE.title);
    } catch {
      setFileError("The sample document could not be loaded.");
    } finally {
      setLoadingSample(false);
    }
  };

  const reset = () => {
    pickToken.current++;
    setFile(null);
    setPlan(null);
    setJob(null);
    setJobError(null);
    setFileError(null);
    setSplitting(false);
    setTitle("");
  };

  const ingest = async () => {
    if (!file || !plan || running) return;
    setUploading(true);
    setJob(null);
    setJobError(null);
    setPollFailures(0);
    try {
      const started = await documents.ingest(file, { title, language });
      setJob(started.job);
    } catch (e) {
      setJobError(documentsErrorText(e));
    } finally {
      setUploading(false);
    }
  };

  // Follow the job until it settles; a few failed polls in a row (the API restarting, a blip) are tolerated.
  useEffect(() => {
    if (!job || job.status !== "running" || pollFailures >= MAX_POLL_FAILURES) return;
    let live = true;
    const timer = window.setTimeout(() => {
      documents
        .job(job.id)
        .then((next) => {
          if (!live) return;
          setPollFailures(0);
          setJob(next);
          if (next.status === "done") onIngestedRef.current(next.result?.doc_id ?? next.doc_id);
        })
        .catch((e) => {
          if (!live) return;
          setPollFailures((n) => n + 1);
          setJobError(`Lost touch with the ingest job. ${documentsErrorText(e)}`);
        });
    }, POLL_MS);
    return () => {
      live = false;
      window.clearTimeout(timer);
    };
  }, [job, pollFailures]);

  const onDrop = (e: DragEvent<HTMLLabelElement>) => {
    e.preventDefault();
    setDragging(false);
    void choose(e.dataTransfer.files?.[0]);
  };

  const states = plan ? partStates(plan.parts, job) : null;
  const stepList = job ? steps(job, status) : null;
  const result = job?.status === "done" ? job.result : null;
  const resultPart = (index: number) => result?.parts.find((p) => p.index === index);
  const partPages = plan?.part_pages ?? status?.part_pages ?? 10;
  const maxPages = status ? `Up to ${status.max_pages} pages, ${status.max_mb} MB.` : "";
  const showForm = !!plan && !job && !uploading;
  const stalled = pollFailures >= MAX_POLL_FAILURES;

  return (
    <section className="panel dx-upload" aria-labelledby={`${uid}-h`}>
      <div className="dx-sec-head">
        <h2 id={`${uid}-h`}>Add a document</h2>
        <p className="dx-hint">PDF, PNG, JPEG, or a ZIP of page images. {maxPages}</p>
      </div>

      {!file ? (
        <label
          className={`dx-drop${dragging ? " is-over" : ""}`}
          htmlFor={`${uid}-file`}
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
        >
          <input
            ref={inputRef}
            id={`${uid}-file`}
            type="file"
            accept={ACCEPT}
            className="visually-hidden"
            onChange={(e) => {
              void choose(e.target.files?.[0]);
              e.target.value = "";
            }}
          />
          <UploadSimpleIcon aria-hidden="true" className="dx-drop__icon" />
          <span className="dx-drop__title">Drop a file here, or choose one</span>
          <span className="dx-drop__hint">
            Long documents are split into parts of {partPages} pages, Sarvam Document AI's limit per job, and digitised in parallel.
          </span>
        </label>
      ) : null}
      {!file ? (
        <div className="dx-sample">
          <button type="button" className="btn btn--ghost mp-mini" onClick={() => void trySample()} disabled={loadingSample}>
            {loadingSample ? <CircleNotchIcon aria-hidden="true" className="spin" /> : <FileTextIcon aria-hidden="true" />}
            {loadingSample ? "Loading the sample…" : "Try the sample pricing policy"}
          </button>
          <span className="dx-hint">
            12 pages, so it goes to Sarvam as two parts. It still lists the Starter price that a later demo meeting changed.
          </span>
        </div>
      ) : (
        <div className="dx-file">
          <FileTextIcon aria-hidden="true" className="dx-file__icon" />
          <div className="dx-file__text">
            <p className="dx-file__name">{file.name}</p>
            <p className="dx-file__meta">
              {[bytes(file.size), plan ? plan.kind.toUpperCase() : null, plan ? `${plan.pages} ${plan.pages === 1 ? "page" : "pages"}` : null]
                .filter(Boolean)
                .join(" · ")}
            </p>
          </div>
          {!running ? (
            <button type="button" className="btn btn--ghost mp-mini" onClick={result ? reset : () => inputRef.current?.click()}>
              {result ? "Add another document" : "Choose another file"}
            </button>
          ) : null}
          {/* kept mounted so "Choose another file" can reopen the picker */}
          {!result ? (
            <input
              ref={inputRef}
              type="file"
              accept={ACCEPT}
              className="visually-hidden"
              tabIndex={-1}
              aria-hidden="true"
              onChange={(e) => {
                void choose(e.target.files?.[0]);
                e.target.value = "";
              }}
            />
          ) : null}
        </div>
      )}

      {splitting ? (
        <p className="dx-note" role="status">
          <CircleNotchIcon aria-hidden="true" className="spin" /> Reading pages and planning the split…
        </p>
      ) : null}

      {fileError ? (
        <div className="mp-alert dx-alert" role="alert">
          <p>{fileError}</p>
          <button type="button" className="btn btn--ghost mp-mini" onClick={reset}>
            Start over
          </button>
        </div>
      ) : null}

      {plan && states ? (
        <div className="dx-plan">
          <p className="dx-plan__lead">
            {plan.parts.length === 1
              ? `Fits in one Sarvam job (${partPages} pages or fewer).`
              : `The splitter cuts this into ${plan.parts.length} parts of at most ${partPages} pages, then Sarvam Vision digitises them in parallel.`}
          </p>
          <ol className="dx-parts" aria-label="Parts">
            {plan.parts.map((p) => {
              const st = states.get(p.index) ?? "planned";
              const rp = resultPart(p.index);
              return (
                <li key={p.index} className={`dx-part is-${st}`} style={{ flexGrow: Math.max(1, p.pages) }}>
                  <span className="dx-part__name">
                    Part {p.index + 1} · {pagesLabel(p.first_page, p.last_page)}
                  </span>
                  <span className="dx-part__state">
                    {st === "working" ? <CircleNotchIcon aria-hidden="true" className="spin" /> : null}
                    {st === "done" ? <CheckCircleIcon aria-hidden="true" weight="fill" /> : null}
                    {st === "failed" ? <WarningCircleIcon aria-hidden="true" weight="fill" /> : null}
                    {PART_LABEL[st]}
                    {st === "planned" ? ` · ${bytes(p.bytes)}` : null}
                    {rp?.timings?.total_s ? <span className="tc"> {secs(rp.timings.total_s)}</span> : null}
                  </span>
                </li>
              );
            })}
          </ol>
        </div>
      ) : null}

      {showForm ? (
        <form
          className="dx-ingest"
          onSubmit={(e) => {
            e.preventDefault();
            void ingest();
          }}
        >
          <label className="dx-field">
            <span className="dx-label">Title (optional)</span>
            <input className="field" value={title} onChange={(e) => setTitle(e.target.value)} placeholder={file?.name.replace(/\.[^.]+$/, "")} maxLength={200} />
          </label>
          <label className="dx-field dx-field--narrow">
            <span className="dx-label">Document language</span>
            <select className="field dx-select" value={language} onChange={(e) => setLanguage(e.target.value)}>
              {LANGUAGES.map((l) => (
                <option key={l.code} value={l.code}>
                  {l.name} ({l.code})
                </option>
              ))}
            </select>
          </label>
          <button type="submit" className="btn btn--primary dx-ingest__go" disabled={status?.sarvam_configured === false}>
            Ingest
          </button>
        </form>
      ) : null}

      {uploading ? (
        <p className="dx-note" role="status">
          <CircleNotchIcon aria-hidden="true" className="spin" /> Uploading…
        </p>
      ) : null}

      {job && stepList ? (
        <div className="dx-progress">
          <p className="visually-hidden" aria-live="polite">
            {progressSentence(job, stepList)}
          </p>
          <ol className="dx-steps" aria-label="Ingest steps">
            {stepList.map((s) => (
              <li key={s.stage} className={`dx-step is-${s.state}`}>
                <span className="dx-step__dot" aria-hidden="true">
                  {s.state === "active" ? <CircleNotchIcon className="spin" /> : null}
                  {s.state === "done" ? <CheckCircleIcon weight="fill" /> : null}
                  {s.state === "failed" ? <WarningCircleIcon weight="fill" /> : null}
                </span>
                <span className="dx-step__label">{s.label}</span>
                <span className="dx-step__detail">{s.state === "skipped" ? "Skipped" : s.detail}</span>
                <span className="visually-hidden">
                  {" "}
                  ({s.state === "active" ? "in progress" : s.state})
                </span>
              </li>
            ))}
          </ol>
        </div>
      ) : null}

      {job?.status === "failed" ? (
        <div className="mp-alert dx-alert" role="alert">
          <p>Ingest failed. {job.error}</p>
          <button type="button" className="btn mp-mini" onClick={() => void ingest()}>
            Try again
          </button>
        </div>
      ) : null}

      {jobError && (!job || job.status === "running") ? (
        <div className="mp-alert dx-alert" role="alert">
          <p>{jobError}</p>
          {stalled ? (
            <button type="button" className="btn mp-mini" onClick={() => setPollFailures(0)}>
              Check again
            </button>
          ) : !job ? (
            <button type="button" className="btn mp-mini" onClick={() => void ingest()}>
              Try again
            </button>
          ) : null}
        </div>
      ) : null}

      {result ? (
        <div className="dx-result">
          <p className="dx-result__head">
            <strong>{result.title}</strong> is ready: {result.pages} pages, {result.chunks} passages, in{" "}
            <span className="tc">{secs(result.total_s)}</span>.
          </p>
          {result.summary ? (
            <>
              <RichText className="dx-prose" text={result.summary.text} />
              <p className="dx-prov">Summary by {modelVia(result.summary.model, result.summary.provider)}</p>
            </>
          ) : null}
          <button type="button" className="btn mp-mini" onClick={() => onOpen(result.doc_id)}>
            Open document
          </button>
        </div>
      ) : null}
    </section>
  );
}
