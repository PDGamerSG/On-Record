"""Split uploaded documents into parts Sarvam Document AI accepts, and digitised pages into search chunks.

Document AI processes at most 10 pages per job (PDF pages, or images in a flat ZIP). `split_document`
cuts longer files into consecutive parts and records which source pages each part covers, so page
numbers stay correct after the parts are digitised separately. `chunk_pages` then turns the digitised
pages into heading-aware passages for full-text and vector search.
"""

from __future__ import annotations

import html
import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Literal

from pypdf import PdfReader, PdfWriter
from pypdf.errors import PdfReadError

SARVAM_MAX_PAGES = 10  # Document AI rejects PDFs and ZIPs with more pages than this

Kind = Literal["pdf", "png", "jpeg", "zip"]
CONTENT_TYPES: dict[str, str] = {
    "pdf": "application/pdf",
    "png": "image/png",
    "jpeg": "image/jpeg",
    "zip": "application/zip",
}
_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg")


class DocumentError(ValueError):
    """The upload is not a document we can split (wrong type, unreadable, encrypted or empty)."""


@dataclass(frozen=True)
class DocumentPart:
    """A slice of the source document small enough for one Document AI job."""

    index: int  # 0-based position among the parts
    first_page: int  # 1-based page number in the source document
    last_page: int
    filename: str
    content_type: str
    data: bytes

    @property
    def page_count(self) -> int:
        return self.last_page - self.first_page + 1


@dataclass(frozen=True)
class Page:
    """Digitised text of one source page."""

    number: int  # 1-based page number in the source document
    text: str  # Markdown-like: headings start with "#", tables are "a | b" rows


@dataclass(frozen=True)
class Chunk:
    """A passage for retrieval. `heading` is the nearest section title above it, if any."""

    seq: int
    page_start: int
    page_end: int
    heading: str
    text: str


def detect_kind(data: bytes) -> Kind:
    """Identify the upload from its leading bytes, not its filename."""
    if data.startswith(b"%PDF-"):
        return "pdf"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data.startswith(b"PK\x03\x04"):
        return "zip"
    raise DocumentError("unsupported file type: upload a PDF, PNG, JPEG or a ZIP of page images")


def count_pages(data: bytes) -> int:
    kind = detect_kind(data)
    if kind == "pdf":
        return len(_pdf_reader(data).pages)
    if kind == "zip":
        return len(_zip_images(data))
    return 1


def split_document(filename: str, data: bytes, max_pages: int = SARVAM_MAX_PAGES) -> list[DocumentPart]:
    """Split a PDF or ZIP of page images into parts of at most `max_pages` pages; an image is one part."""
    if isinstance(max_pages, bool) or not isinstance(max_pages, int) or not 1 <= max_pages <= SARVAM_MAX_PAGES:
        raise ValueError(f"max_pages must be an int from 1 to {SARVAM_MAX_PAGES}, got {max_pages!r}")
    if not data:
        raise DocumentError("the file is empty")
    kind = detect_kind(data)
    stem = PurePosixPath(filename or "document").stem or "document"
    if kind == "pdf":
        return _split_pdf(stem, data, max_pages)
    if kind == "zip":
        return _split_zip(stem, data, max_pages)
    suffix = ".png" if kind == "png" else ".jpg"
    return [DocumentPart(0, 1, 1, f"{stem}{suffix}", CONTENT_TYPES[kind], data)]


def _pdf_reader(data: bytes) -> PdfReader:
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            raise DocumentError("the PDF is password-protected")
        if not reader.pages:
            raise DocumentError("the PDF has no pages")
    except DocumentError:
        raise
    except (PdfReadError, ValueError, OSError, KeyError) as exc:
        raise DocumentError(f"the PDF could not be read: {exc}") from exc
    return reader


def _split_pdf(stem: str, data: bytes, max_pages: int) -> list[DocumentPart]:
    reader = _pdf_reader(data)
    total = len(reader.pages)
    if total <= max_pages:  # already small enough: send the original bytes untouched
        return [DocumentPart(0, 1, total, f"{stem}.pdf", CONTENT_TYPES["pdf"], data)]
    parts = []
    for index, start in enumerate(range(0, total, max_pages)):
        end = min(start + max_pages, total)
        writer = PdfWriter()
        for page in reader.pages[start:end]:
            writer.add_page(page)
        buffer = io.BytesIO()
        writer.write(buffer)
        name = f"{stem}.part{index + 1:02d}-p{start + 1}-{end}.pdf"
        parts.append(DocumentPart(index, start + 1, end, name, CONTENT_TYPES["pdf"], buffer.getvalue()))
    return parts


def _zip_images(data: bytes) -> list[tuple[str, bytes]]:
    """Page images in filename order (Document AI orders ZIP pages by filename)."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = sorted(
                info.filename
                for info in archive.infolist()
                if not info.is_dir()
                and info.filename.lower().endswith(_IMAGE_SUFFIXES)
                and not PurePosixPath(info.filename).name.startswith(".")
                and "__MACOSX" not in info.filename
            )
            images = [(PurePosixPath(name).name, archive.read(name)) for name in names]
    except (zipfile.BadZipFile, OSError) as exc:
        raise DocumentError(f"the ZIP could not be read: {exc}") from exc
    if not images:
        raise DocumentError("the ZIP has no PNG or JPEG page images")
    if len({name for name, _ in images}) != len(images):
        raise DocumentError("the ZIP has two page images with the same filename")
    return images


def _split_zip(stem: str, data: bytes, max_pages: int) -> list[DocumentPart]:
    images = _zip_images(data)
    parts = []
    for index, start in enumerate(range(0, len(images), max_pages)):
        batch = images[start:start + max_pages]
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archive:  # flat, as Document AI requires
            for name, content in batch:
                archive.writestr(name, content)
        end = start + len(batch)
        name = f"{stem}.part{index + 1:02d}-p{start + 1}-{end}.zip"
        parts.append(DocumentPart(index, start + 1, end, name, CONTENT_TYPES["zip"], buffer.getvalue()))
    return parts


# ------------------------------------------------------------------------------------ digitised pages

_SKIPPED_TAGS = frozenset({"header", "footer", "page-number"})  # running headers repeat on every page
_HEADING_TAGS = {"title": "#", "headline": "#", "section-title": "##"}
_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
_CELL = re.compile(r"<t[hd][^>]*>(.*?)</t[hd]>", re.IGNORECASE | re.DOTALL)
_TAG = re.compile(r"<[^>]+>")


def html_table_text(markup: str) -> str:
    """Flatten an HTML table into one "cell | cell" line per row."""
    rows = []
    for row in _ROW.findall(markup):
        cells = [" ".join(html.unescape(_TAG.sub(" ", cell)).split()) for cell in _CELL.findall(row)]
        if any(cells):
            rows.append(" | ".join(cells))
    return "\n".join(rows) if rows else " ".join(html.unescape(_TAG.sub(" ", markup)).split())


def page_text(blocks: list[dict]) -> str:
    """Markdown-like text of one page from Document AI layout blocks, in reading order."""
    ordered = sorted(
        (b for b in blocks if isinstance(b, dict) and isinstance(b.get("text"), str)),
        key=lambda b: (b.get("reading_order") is None, b.get("reading_order") or 0),
    )
    lines = []
    for block in ordered:
        tag = str(block.get("layout_tag") or "paragraph").lower()
        text = block["text"].strip()
        if not text or tag in _SKIPPED_TAGS:
            continue
        if tag == "table" or text.lstrip().lower().startswith("<table"):
            text = html_table_text(text)
        elif tag in _HEADING_TAGS and not text.startswith("#"):
            text = f"{_HEADING_TAGS[tag]} {text}"
        lines.append(text)
    return "\n\n".join(lines)


# --------------------------------------------------------------------------------------------- chunks

_HEADING_LINE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_SENTENCE_END = re.compile(r"(?<=[.!?।])\s+")


def chunk_pages(pages: list[Page], max_chars: int = 1200) -> list[Chunk]:
    """Group paragraphs into passages of at most `max_chars` characters.

    A heading closes the current passage, so every passage sits under one section heading. Passages may
    span a page break; page_start/page_end record the range. A paragraph longer than `max_chars` is split
    at sentence ends (or hard-wrapped if it has none).
    """
    if max_chars < 100:
        raise ValueError("max_chars must be at least 100")
    chunks: list[Chunk] = []
    heading = ""
    buffer: list[str] = []
    size = 0
    span: list[int] = []

    def flush() -> None:
        nonlocal buffer, size, span
        text = "\n\n".join(buffer).strip()
        if text:
            chunks.append(Chunk(len(chunks), span[0], span[-1], heading, text))
        buffer, size, span = [], 0, []

    for page in sorted(pages, key=lambda p: p.number):
        for paragraph in re.split(r"\n\s*\n", page.text or ""):
            paragraph = paragraph.strip()
            if not paragraph:
                continue
            match = _HEADING_LINE.match(paragraph)
            if match and "\n" not in paragraph:
                flush()
                heading = match.group(2).strip()
                continue
            for piece in _pieces(paragraph, max_chars):
                if size and size + len(piece) + 2 > max_chars:
                    flush()
                buffer.append(piece)
                size += len(piece) + 2
                span.append(page.number)
    flush()
    return chunks


def _pieces(paragraph: str, max_chars: int) -> list[str]:
    if len(paragraph) <= max_chars:
        return [paragraph]
    pieces: list[str] = []
    current = ""
    for sentence in _SENTENCE_END.split(paragraph):
        while len(sentence) > max_chars:  # no usable sentence break: hard-wrap at a space if possible
            cut = sentence.rfind(" ", 0, max_chars)
            cut = cut if cut > max_chars // 2 else max_chars
            if current:
                pieces.append(current)
                current = ""
            pieces.append(sentence[:cut].strip())
            sentence = sentence[cut:].strip()
        if current and len(current) + len(sentence) + 1 > max_chars:
            pieces.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        pieces.append(current)
    return [p for p in pieces if p]
