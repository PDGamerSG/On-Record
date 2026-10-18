"""Document ingestion: split -> Sarvam Document AI (parts in parallel) -> chunk -> embed -> graph.

Page numbers from each digitised part are shifted back to source-document numbering before chunking,
so a citation such as "p. 14" points at the right page of the original upload.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Callable
from typing import Any, Protocol

from ..contracts import LLM, Embedder
from ..graph.text import slug
from .split import SARVAM_MAX_PAGES, Chunk, DocumentError, DocumentPart, Page, chunk_pages, split_document
from .store import DocumentStore

log = logging.getLogger(__name__)

Progress = Callable[[dict[str, Any]], None]


class Digitiser(Protocol):
    async def digitise(self, filename: str, data: bytes, content_type: str, language: str = "en-IN") -> Any: ...


def embed_text(title: str, chunk: Chunk) -> str:
    """What gets embedded: the passage with its document and section for context."""
    context = " > ".join(part for part in (title, chunk.heading) if part)
    return f"{context}\n{chunk.text}" if context else chunk.text


def new_document_id(filename: str) -> str:
    return f"doc-{slug(filename or 'document', 24) or 'document'}-{uuid.uuid4().hex[:8]}"


class DocumentIngestor:
    def __init__(
        self,
        docs: DocumentStore,
        embedder: Embedder,
        digitiser: Digitiser,
        *,
        llm: LLM | None = None,
        language: str = "en-IN",
        max_pages: int = SARVAM_MAX_PAGES,
        max_total_pages: int = 100,
        concurrency: int = 3,
        chunk_chars: int = 1200,
    ) -> None:
        if concurrency < 1 or max_total_pages < 1:
            raise ValueError("concurrency and max_total_pages must be positive")
        self.docs = docs
        self.embedder = embedder
        self.digitiser = digitiser
        self.llm = llm
        self.language = language
        self.max_pages = max_pages
        self.max_total_pages = max_total_pages
        self.concurrency = concurrency
        self.chunk_chars = chunk_chars
        self._schema_ready = False

    def plan(self, filename: str, data: bytes) -> list[DocumentPart]:
        """Split the upload and enforce the page budget, without calling Sarvam."""
        parts = split_document(filename, data, self.max_pages)
        total = parts[-1].last_page
        if total > self.max_total_pages:
            raise DocumentError(f"the document has {total} pages; the limit is {self.max_total_pages}")
        return parts

    async def ingest(
        self,
        filename: str,
        data: bytes,
        *,
        title: str | None = None,
        doc_id: str | None = None,
        language: str | None = None,
        summarise: bool = True,
        on_progress: Progress | None = None,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        language = language or self.language
        doc_id = doc_id or new_document_id(filename)
        title = (title or "").strip() or filename
        report = on_progress or (lambda event: None)

        parts = self.plan(filename, data)
        total_pages = parts[-1].last_page
        report({"stage": "split", "doc_id": doc_id, "parts": len(parts), "pages": total_pages})

        gate = asyncio.Semaphore(self.concurrency)
        done = 0

        async def digitise(part: DocumentPart) -> tuple[DocumentPart, Any]:
            nonlocal done
            async with gate:
                result = await self.digitiser.digitise(part.filename, part.data, part.content_type, language)
            done += 1
            report({"stage": "digitise", "doc_id": doc_id, "part": part.index, "done": done, "parts": len(parts),
                    "first_page": part.first_page, "last_page": part.last_page})
            return part, result

        results = await asyncio.gather(*(digitise(part) for part in parts))
        pages = _source_pages(results)
        chunks = chunk_pages(pages, max_chars=self.chunk_chars)
        if not chunks:
            raise DocumentError("Sarvam Document AI found no text in this document")
        report({"stage": "chunk", "doc_id": doc_id, "chunks": len(chunks)})

        embeddings = await asyncio.to_thread(self.embedder.embed_documents, [embed_text(title, c) for c in chunks])
        report({"stage": "embed", "doc_id": doc_id, "chunks": len(chunks), "embedder": self.embedder.name})

        if not self._schema_ready:
            await asyncio.to_thread(self.docs.ensure_schema, self.embedder.dim)
            self._schema_ready = True
        written = await asyncio.to_thread(
            self.docs.write_document,
            doc_id,
            title=title,
            filename=filename,
            language=language,
            pages=total_pages,
            parts=len(parts),
            size=len(data),
            chunks=chunks,
            embeddings=embeddings,
            embedder=self.embedder.name,
            digitised_by="Sarvam Vision (Document AI)",
        )
        report({"stage": "store", "doc_id": doc_id, "written": written["written"]})

        summary = None
        if summarise and self.llm is not None:
            from .answer import summarise_document  # local import: answer.py depends on the retriever

            try:
                summary = await summarise_document(self.llm, title, chunks)
                await asyncio.to_thread(self.docs.set_summary, doc_id, summary["text"], summary["model"])
                report({"stage": "summary", "doc_id": doc_id, "model": summary["model"]})
            except Exception as exc:  # noqa: BLE001 - a summary is optional; the document is already stored
                log.warning("summary for %s failed: %r", doc_id, exc)

        return {
            "doc_id": doc_id,
            "title": title,
            "pages": total_pages,
            "chunks": len(chunks),
            "summary": summary,
            "parts": [
                {
                    "index": part.index,
                    "filename": part.filename,
                    "first_page": part.first_page,
                    "last_page": part.last_page,
                    "job_id": getattr(result, "job_id", None),
                    "status": getattr(result, "status", None),
                    "pages_failed": getattr(result, "pages_failed", 0),
                    "timings": getattr(result, "timings", {}),
                }
                for part, result in results
            ],
            "total_s": round(time.perf_counter() - started, 2),
        }


def _source_pages(results: list[tuple[DocumentPart, Any]]) -> list[Page]:
    pages: list[Page] = []
    for part, result in results:
        for page in result.pages:
            if not 1 <= page.number <= part.page_count:
                log.warning("part %s returned page %s outside 1..%s", part.filename, page.number, part.page_count)
                continue
            pages.append(Page(part.first_page + page.number - 1, page.text))
    return sorted(pages, key=lambda p: p.number)
