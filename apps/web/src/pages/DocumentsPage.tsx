import { useCallback, useEffect, useId, useState } from "react";
import { ArrowClockwiseIcon, FileTextIcon, TrashIcon } from "@phosphor-icons/react";
import {
  documents,
  documentsErrorText,
  isUnreachable,
  languageName,
  modelVia,
  pagesLabel,
  type DocumentDetail,
  type DocumentsStatus,
  type DocumentSummary,
} from "../api/documents";
import { when } from "../lib/format";
import DocAsk from "../components/documents/DocAsk";
import DocUpload from "../components/documents/DocUpload";
import RichText from "../components/documents/RichText";
import "./memoryPages.css";
import "./DocumentsPage.css";

const START_CMD = "uv run --project apps/api uvicorn wsw_brain.documents.app:app --port 8000";

const newestFirst = (a: DocumentSummary, b: DocumentSummary) => (Number(b.created_at) || 0) - (Number(a.created_at) || 0);

function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

function sizeLabel(n: number): string {
  if (!n) return "";
  return n >= 1024 * 1024 ? `${(n / (1024 * 1024)).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`;
}

/** "Sarvam Vision (Document AI)" -> "Sarvam Vision" */
function shortName(s: string | null | undefined): string {
  return (s ?? "").replace(/\s*\(.*\)\s*$/, "");
}

export default function DocumentsPage() {
  const [status, setStatus] = useState<DocumentsStatus | null>(null);
  const [docs, setDocs] = useState<DocumentSummary[] | null>(null);
  const [offline, setOffline] = useState(false);
  const [listError, setListError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  const [scope, setScope] = useState("");

  const reload = useCallback(() => setNonce((n) => n + 1), []);

  useEffect(() => {
    let live = true;
    Promise.allSettled([documents.status(), documents.list()]).then(([s, l]) => {
      if (!live) return;
      const down = (s.status === "rejected" && isUnreachable(s.reason)) || (l.status === "rejected" && isUnreachable(l.reason));
      setOffline(down);
      if (s.status === "fulfilled") setStatus(s.value);
      if (l.status === "fulfilled") {
        const list = Array.isArray(l.value) ? [...l.value].sort(newestFirst) : [];
        setDocs(list);
        setListError(null);
        // keep the selection if it still exists, else open the newest document
        setSelected((cur) => (cur && list.some((d) => d.id === cur) ? cur : (list[0]?.id ?? null)));
      } else if (!down) {
        setListError(documentsErrorText(l.reason));
      }
    });
    return () => {
      live = false;
    };
  }, [nonce]);

  const select = (id: string) => {
    setSelected(id);
    setScope(id);
  };

  const onIngested = useCallback(
    (docId: string) => {
      setSelected(docId);
      setScope(docId);
      reload();
    },
    [reload],
  );

  const onDeleted = (id: string) => {
    setScope((s) => (s === id ? "" : s));
    setSelected((cur) => (cur === id ? null : cur));
    setDocs((list) => (list ? list.filter((d) => d.id !== id) : list));
    reload();
  };

  const llm = status ? modelVia(status.llm.model, status.llm.provider) : "";

  return (
    <div className="mp dx">
      <header className="mp-head">
        <div>
          <h1>Documents</h1>
          <p className="mp-sub">Upload a PDF or page scans; Sarvam Vision reads every page and Gemma 4 answers questions with page citations.</p>
          {status ? (
            <p className="mp-count dx-status">
              <span>Digitiser: {status.digitiser}</span>
              <span>LLM: {llm}</span>
              <span>Embedder: {status.embedder}</span>
              <span>Splits into parts of {status.part_pages} pages</span>
            </p>
          ) : null}
        </div>
      </header>

      {offline ? (
        <div className="panel mp-empty dx-offline" role="status">
          <h2>The documents API isn't running</h2>
          <p>Start the documents API, then try again:</p>
          <pre className="dx-cmd">
            <code>{START_CMD}</code>
          </pre>
          <button type="button" className="btn" onClick={reload}>
            <ArrowClockwiseIcon aria-hidden="true" />
            Try again
          </button>
        </div>
      ) : (
        <>
          {status && !status.sarvam_configured ? (
            <div className="mp-alert" role="alert">
              <p>SARVAM_API_KEY isn't set on the server, so new uploads can't be digitised and questions can't be answered by Gemma 4.</p>
            </div>
          ) : null}

          <DocUpload status={status} onIngested={onIngested} onOpen={select} />

          <div className="dx-main">
            <Library docs={docs} error={listError} selected={selected} onSelect={select} onRetry={reload} />
            <div className="dx-col">
              <DocAsk docs={docs ?? []} scope={scope} onScope={setScope} />
              {selected ? <DocumentView key={selected} id={selected} status={status} onDeleted={onDeleted} /> : null}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

interface LibraryProps {
  docs: DocumentSummary[] | null;
  error: string | null;
  selected: string | null;
  onSelect: (id: string) => void;
  onRetry: () => void;
}

function Library({ docs, error, selected, onSelect, onRetry }: LibraryProps) {
  const uid = useId();
  return (
    <section className="panel dx-lib" aria-labelledby={`${uid}-h`}>
      <h2 className="dx-lib__h" id={`${uid}-h`}>
        Library
        {docs ? <span className="cm-owner__count">{docs.length}</span> : null}
      </h2>
      {error ? (
        <div className="mp-alert dx-alert" role="alert">
          <p>Documents didn't load. {error}</p>
          <button type="button" className="btn mp-mini" onClick={onRetry}>
            Try again
          </button>
        </div>
      ) : null}
      {!docs && !error ? (
        <div className="dx-lib__skel" aria-hidden="true">
          <span className="skel mp-skel__line" />
          <span className="skel mp-skel__line mp-skel__line--short" />
        </div>
      ) : null}
      {docs && !docs.length ? <p className="dx-lib__empty">No documents yet. Add a PDF above and it will appear here.</p> : null}
      {docs?.length ? (
        <ul className="dx-lib__list">
          {docs.map((d) => {
            const on = d.id === selected;
            return (
              <li key={d.id}>
                <button type="button" className={`dx-doc${on ? " is-on" : ""}`} aria-pressed={on} onClick={() => onSelect(d.id)}>
                  <FileTextIcon aria-hidden="true" weight={on ? "fill" : "regular"} className="dx-doc__icon" />
                  <span className="dx-doc__text">
                    <span className="dx-doc__title">{d.title || d.filename}</span>
                    <span className="dx-doc__meta">
                      {[plural(d.pages, "page"), plural(d.parts, "part"), plural(d.chunk_count, "passage")].join(" · ")}
                    </span>
                    <span className="dx-doc__meta">{[languageName(d.language), when(d.created_at)].filter(Boolean).join(" · ")}</span>
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      ) : null}
    </section>
  );
}

interface ViewProps {
  id: string;
  status: DocumentsStatus | null;
  onDeleted: (id: string) => void;
}

function DocumentView({ id, status, onDeleted }: ViewProps) {
  const uid = useId();
  const [doc, setDoc] = useState<DocumentDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    documents
      .get(id)
      .then((d) => {
        if (!live) return;
        setDoc(d);
        setError(null);
      })
      .catch((e) => {
        if (live) setError(documentsErrorText(e));
      });
    return () => {
      live = false;
    };
  }, [id, nonce]);

  const remove = async () => {
    if (!doc) return;
    if (!window.confirm(`Delete “${doc.title}”? Its passages are removed from the graph and it can't be asked about any more.`)) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      await documents.remove(doc.id);
      onDeleted(doc.id);
    } catch (e) {
      setDeleteError(documentsErrorText(e));
      setDeleting(false);
    }
  };

  if (error) {
    return (
      <div className="mp-alert" role="alert">
        <p>That document didn't load. {error}</p>
        <button type="button" className="btn mp-mini" onClick={() => setNonce((n) => n + 1)}>
          Try again
        </button>
      </div>
    );
  }

  if (!doc) {
    return (
      <div className="panel mp-skel" aria-hidden="true">
        <span className="skel mp-skel__head" />
        <span className="skel mp-skel__line" />
        <span className="skel mp-skel__line mp-skel__line--short" />
      </div>
    );
  }

  const summaryBy =
    doc.summary_model && status && status.llm.model === doc.summary_model
      ? modelVia(doc.summary_model, status.llm.provider)
      : modelVia(doc.summary_model, null);
  const chunks = [...(doc.chunks ?? [])].sort((a, b) => a.seq - b.seq);

  return (
    <article className="panel dx-view" aria-labelledby={`${uid}-h`}>
      <header className="dx-view__head">
        <div className="dx-view__titles">
          <h2 id={`${uid}-h`}>{doc.title || doc.filename}</h2>
          <p className="mp-meta dx-view__meta">
            <span>{doc.filename}</span>
            <span>{plural(doc.pages, "page")}</span>
            <span>{plural(doc.parts, "part")}</span>
            <span>{plural(doc.chunk_count, "passage")}</span>
            <span>{languageName(doc.language)}</span>
            {doc.bytes ? <span>{sizeLabel(doc.bytes)}</span> : null}
            {doc.created_at ? <span>{when(doc.created_at)}</span> : null}
          </p>
        </div>
        <button type="button" className="btn btn--ghost mp-mini dx-delete" onClick={() => void remove()} disabled={deleting}>
          <TrashIcon aria-hidden="true" />
          {deleting ? "Deleting…" : "Delete"}
        </button>
      </header>

      {deleteError ? (
        <div className="mp-alert dx-alert" role="alert">
          <p>Couldn't delete it. {deleteError}</p>
        </div>
      ) : null}

      <p className="dx-prov dx-view__prov">
        {[
          doc.digitised_by ? `Digitised by ${shortName(doc.digitised_by)}` : "",
          doc.embedder ? `Embedded with ${doc.embedder}` : "",
          doc.summary && summaryBy ? `Summary by ${summaryBy}` : "",
        ]
          .filter(Boolean)
          .join(" · ")}
      </p>

      <section className="dx-view__summary" aria-label="Summary">
        <h3 className="dx-h3">Summary</h3>
        {doc.summary ? <RichText className="dx-prose" text={doc.summary} /> : <p className="dx-muted">No summary was written for this document.</p>}
      </section>

      <section className="dx-view__chunks" aria-label="Passages">
        <h3 className="dx-h3">
          Passages <span className="cm-owner__count">{chunks.length}</span>
        </h3>
        {chunks.length ? (
          <ol className="dx-chunks">
            {chunks.map((c) => (
              <li key={c.id}>
                <details className="dx-chunk">
                  <summary>
                    <span className="dx-chunk__pages tc">{pagesLabel(c.page_start, c.page_end)}</span>
                    <span className="dx-chunk__heading">{c.heading || `Passage ${c.seq + 1}`}</span>
                  </summary>
                  <p className="dx-chunk__text">{c.text}</p>
                </details>
              </li>
            ))}
          </ol>
        ) : (
          <p className="dx-muted">No passages stored.</p>
        )}
      </section>
    </article>
  );
}
