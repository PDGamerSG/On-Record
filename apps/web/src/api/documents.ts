// Client for the documents API (/api/documents...). It talks to the server directly with fetch rather than through the
// demo-aware `api` proxy in client.ts: the documents service has no /api/health, so the app may be in demo mode while
// documents still work, and when the service is down the page says so instead of showing bundled data.
import { API_BASE } from "./base";

export type DocKind = "pdf" | "png" | "jpeg" | "zip";
export type JobStatus = "running" | "done" | "failed";
export type DocStage = "split" | "digitise" | "vision" | "chunk" | "embed" | "store" | "summary";

export interface DocumentsStatus {
  sarvam_configured: boolean;
  digitiser: string;
  llm: { provider: string; model: string };
  embedder: string;
  part_pages: number;
  max_pages: number;
  max_mb: number;
  language: string;
}

export interface SplitPart {
  index: number;
  filename: string;
  first_page: number;
  last_page: number;
  pages: number;
  bytes: number;
}

export interface SplitPlan {
  filename: string;
  kind: DocKind;
  pages: number;
  part_pages: number;
  parts: SplitPart[];
}

export interface JobEvent {
  stage: DocStage;
  at: number;
  doc_id?: string;
  /** split */
  parts?: number;
  pages?: number;
  /** digitise: the 0-based part that just finished, and how many have finished so far */
  part?: number;
  done?: number;
  first_page?: number;
  last_page?: number;
  /** chunk, embed */
  chunks?: number;
  embedder?: string;
  /** store */
  written?: number;
  /** summary, vision (image uploads: Gemma 4 described the image) */
  model?: string;
}

export interface ResultPart {
  index: number;
  filename: string;
  first_page: number;
  last_page: number;
  job_id: string | null;
  status: string;
  pages_failed?: number[] | number | null;
  timings?: { submit_s?: number; process_s?: number; total_s?: number } | null;
}

export interface IngestResult {
  doc_id: string;
  title: string;
  pages: number;
  chunks: number;
  total_s: number;
  summary: { text: string; model: string; provider: string } | null;
  parts: ResultPart[];
  /** part indexes whose image Gemma 4 described (PNG/JPEG uploads) */
  visual?: number[];
}

export interface Job {
  id: string;
  doc_id: string;
  filename: string;
  status: JobStatus;
  events: JobEvent[];
  result: IngestResult | null;
  error: string | null;
}

export interface IngestStarted {
  job: Job;
  pages: number;
  parts: number;
}

export interface DocumentSummary {
  id: string;
  title: string;
  filename: string;
  language: string;
  pages: number;
  parts: number;
  bytes: number;
  created_at: number;
  status: string;
  summary: string | null;
  summary_model: string | null;
  embedder: string;
  digitised_by: string;
  chunk_count: number;
}

export interface DocChunk {
  id: string;
  seq: number;
  page_start: number;
  page_end: number;
  heading: string | null;
  text: string;
}

export interface DocumentDetail extends DocumentSummary {
  chunks: DocChunk[];
}

export interface DocHit {
  id: string;
  seq: number;
  page_start: number;
  page_end: number;
  heading: string | null;
  text: string;
  doc_id: string;
  doc_title: string;
  score: number;
  via: "fulltext" | "vector" | string;
}

/** A meeting line retrieved alongside document passages (ask with include_meetings). */
export interface MeetingHit {
  utterance_id: string;
  meeting_id: string;
  meeting_title: string;
  speaker: string;
  speaker_name: string | null;
  t_start: number;
  t_end: number;
  text: string;
  score: number;
  via: string;
  meeting_date?: string;
}

export interface DocAnswer {
  answer: string;
  citations: DocHit[];
  hits: DocHit[];
  model: string | null;
  provider: string | null;
  timings: { retrieval_ms?: number; model_ms?: number; translate_ms?: number } & Record<string, number | undefined>;
  /** present when a reply language other than en-IN was asked for and Sarvam Mayura translated the answer */
  translated_answer?: string;
  answer_language?: string;
  translated_by?: string;
  /** present instead of translated_answer when the translation failed */
  translation_error?: string;
  /** present when include_meetings was set */
  meeting_citations?: MeetingHit[];
  meeting_hits?: MeetingHit[];
}

export interface SpokenAudio {
  blob: Blob;
  /** from the x-spoken-by header, e.g. "Sarvam Bulbul v3" */
  spokenBy: string | null;
}

export class DocumentsError extends Error {
  /** HTTP status; 0 when the request never reached the documents API */
  status: number;
  /** true when no documents API answered (network error, proxy error, or a server without these routes) */
  unreachable: boolean;
  constructor(status: number, message: string, unreachable = false) {
    super(message);
    this.name = "DocumentsError";
    this.status = status;
    this.unreachable = unreachable;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/documents${path}`, init);
  } catch {
    throw new DocumentsError(0, "The documents API isn't reachable.", true);
  }
  const isJson = (res.headers.get("content-type") ?? "").includes("application/json");
  const body: unknown = isJson ? await res.json().catch(() => null) : null;
  if (!res.ok) {
    const detail = body && typeof body === "object" && "detail" in body ? (body as { detail: unknown }).detail : null;
    const message =
      typeof detail === "string" ? detail : Array.isArray(detail) ? "The request was rejected." : `Request failed (${res.status}).`;
    // A proxy error (no JSON), or a server that doesn't know these routes, means the documents API isn't running here.
    const unreachable = !isJson || res.status === 502 || res.status === 503 || res.status === 504 || (res.status === 404 && detail === "Not Found");
    throw new DocumentsError(res.status, message, unreachable);
  }
  if (!isJson) throw new DocumentsError(res.status, "The documents API isn't reachable.", true);
  return body as T;
}

function form(file: File, fields: Record<string, string | undefined> = {}): FormData {
  const data = new FormData();
  data.append("file", file, file.name);
  for (const [k, v] of Object.entries(fields)) if (v) data.append(k, v);
  return data;
}

export const documents = {
  status: () => request<DocumentsStatus>("/status"),
  split: (file: File) => request<SplitPlan>("/split", { method: "POST", body: form(file) }),
  ingest: (file: File, opts: { title?: string; language?: string } = {}) =>
    request<IngestStarted>("", { method: "POST", body: form(file, { title: opts.title?.trim(), language: opts.language }) }),
  job: (jobId: string) => request<Job>(`/jobs/${encodeURIComponent(jobId)}`),
  list: () => request<DocumentSummary[]>(""),
  get: (id: string) => request<DocumentDetail>(`/${encodeURIComponent(id)}`),
  remove: (id: string) => request<{ deleted: boolean }>(`/${encodeURIComponent(id)}`, { method: "DELETE" }),
  ask: (body: { question: string; doc_id?: string | null; k?: number; language?: string; include_meetings?: boolean }) =>
    request<DocAnswer>("/ask", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
  /** Speech for an answer (citation markers are stripped by the server), as WAV bytes. */
  speak: async (body: { text: string; language: string; speaker?: string; pace?: number }, signal?: AbortSignal): Promise<SpokenAudio> => {
    let res: Response;
    try {
      res = await fetch(`${API_BASE}/api/documents/speak`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        signal,
      });
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") throw e;
      throw new DocumentsError(0, "The documents API isn't reachable.", true);
    }
    if (!res.ok) {
      const data: unknown = await res.json().catch(() => null);
      const detail = data && typeof data === "object" && "detail" in data ? (data as { detail: unknown }).detail : null;
      throw new DocumentsError(res.status, typeof detail === "string" ? detail : `Speech failed (${res.status}).`);
    }
    return { blob: await res.blob(), spokenBy: res.headers.get("x-spoken-by") };
  },
  search: (q: string, docId?: string | null) => {
    const params = new URLSearchParams({ q });
    if (docId) params.set("doc_id", docId);
    return request<DocHit[]>(`/search?${params.toString()}`);
  },
};

export function documentsErrorText(e: unknown): string {
  if (e instanceof Error) return e.message;
  return String(e);
}

export function isUnreachable(e: unknown): boolean {
  return e instanceof DocumentsError && e.unreachable;
}

export const LANGUAGES: { code: string; name: string }[] = [
  { code: "en-IN", name: "English" },
  { code: "hi-IN", name: "Hindi" },
  { code: "kn-IN", name: "Kannada" },
  { code: "ta-IN", name: "Tamil" },
  { code: "te-IN", name: "Telugu" },
  { code: "mr-IN", name: "Marathi" },
  { code: "bn-IN", name: "Bengali" },
  { code: "gu-IN", name: "Gujarati" },
  { code: "ml-IN", name: "Malayalam" },
  { code: "pa-IN", name: "Punjabi" },
  { code: "od-IN", name: "Odia" },
];

/** Languages Sarvam Bulbul can speak. */
export const SPEAKABLE = new Set(["bn-IN", "en-IN", "gu-IN", "hi-IN", "kn-IN", "ml-IN", "mr-IN", "od-IN", "pa-IN", "ta-IN", "te-IN"]);

export function languageName(code: string | null | undefined): string {
  if (!code) return "";
  return LANGUAGES.find((l) => l.code === code)?.name ?? code;
}

/** "p. 4" or "pp. 2–3" */
export function pagesLabel(first: number, last: number): string {
  return !last || first === last ? `p. ${first}` : `pp. ${first}–${last}`;
}

const MODEL_NAMES: Record<string, string> = { gemma4: "Gemma 4", "gemma-4": "Gemma 4" };
const PROVIDER_NAMES: Record<string, string> = { sarvam: "Sarvam", ollama: "Ollama", gemini: "the Gemini API", openai: "an OpenAI-compatible server" };

export function modelName(model: string | null | undefined): string {
  if (!model) return "";
  const key = model.toLowerCase();
  return MODEL_NAMES[key] ?? (key.startsWith("gemma4") || key.startsWith("gemma-4") ? `Gemma 4 (${model})` : model);
}

export function providerName(provider: string | null | undefined): string {
  if (!provider) return "";
  return PROVIDER_NAMES[provider.toLowerCase()] ?? provider.charAt(0).toUpperCase() + provider.slice(1);
}

/** "Gemma 4 via Sarvam" */
export function modelVia(model: string | null | undefined, provider: string | null | undefined): string {
  const m = modelName(model);
  const p = providerName(provider);
  if (m && p) return `${m} via ${p}`;
  return m || (p ? `a model via ${p}` : "");
}
