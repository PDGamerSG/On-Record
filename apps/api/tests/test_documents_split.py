"""Splitting uploads for Sarvam Document AI and chunking digitised pages; no network or models."""

import io
import zipfile

import pytest
from pypdf import PdfReader, PdfWriter

from wsw_brain.documents.split import (
    SARVAM_MAX_PAGES,
    DocumentError,
    Page,
    chunk_pages,
    count_pages,
    detect_kind,
    html_table_text,
    page_text,
    split_document,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32
JPEG = b"\xff\xd8\xff" + b"0" * 32


def make_pdf(pages: int) -> bytes:
    writer = PdfWriter()
    for index in range(pages):
        writer.add_blank_page(width=200 + index, height=300)  # width encodes the source page number
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def make_zip(names: list[str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name in names:
            archive.writestr(name, PNG)
    return buffer.getvalue()


def widths(data: bytes) -> list[int]:
    return [round(float(page.mediabox.width)) - 200 for page in PdfReader(io.BytesIO(data)).pages]


def test_detect_kind_uses_leading_bytes():
    assert detect_kind(make_pdf(1)) == "pdf"
    assert detect_kind(PNG) == "png"
    assert detect_kind(JPEG) == "jpeg"
    assert detect_kind(make_zip(["a.png"])) == "zip"
    with pytest.raises(DocumentError, match="unsupported"):
        detect_kind(b"hello")


def test_short_pdf_is_sent_unchanged():
    data = make_pdf(4)
    parts = split_document("notes.pdf", data)
    assert len(parts) == 1
    assert parts[0].data == data
    assert (parts[0].first_page, parts[0].last_page, parts[0].filename) == (1, 4, "notes.pdf")


def test_long_pdf_splits_into_ten_page_parts_in_order():
    parts = split_document("contract.pdf", make_pdf(23))
    assert [(p.first_page, p.last_page) for p in parts] == [(1, 10), (11, 20), (21, 23)]
    assert [p.page_count for p in parts] == [10, 10, 3]
    assert parts[1].filename == "contract.part02-p11-20.pdf"
    assert widths(parts[1].data) == list(range(10, 20))
    assert all(len(PdfReader(io.BytesIO(p.data)).pages) <= SARVAM_MAX_PAGES for p in parts)


def test_smaller_part_size_and_validation():
    parts = split_document("a.pdf", make_pdf(7), max_pages=3)
    assert [(p.first_page, p.last_page) for p in parts] == [(1, 3), (4, 6), (7, 7)]
    for bad in (0, 11, True, "3"):
        with pytest.raises(ValueError):
            split_document("a.pdf", make_pdf(2), max_pages=bad)


def test_images_are_one_page_parts():
    [part] = split_document("scan.jpeg", JPEG)
    assert (part.first_page, part.last_page, part.content_type, part.filename) == (1, 1, "image/jpeg", "scan.jpg")


def test_zip_of_images_splits_by_filename_order_and_stays_flat():
    names = [f"pages/page_{n:02d}.png" for n in range(12, 0, -1)] + ["__MACOSX/._x.png", "readme.txt"]
    parts = split_document("bundle.zip", make_zip(names))
    assert [(p.first_page, p.last_page) for p in parts] == [(1, 10), (11, 12)]
    with zipfile.ZipFile(io.BytesIO(parts[1].data)) as archive:
        assert archive.namelist() == ["page_11.png", "page_12.png"]
    assert count_pages(make_zip(names)) == 12


def test_unusable_uploads_raise_document_error():
    with pytest.raises(DocumentError, match="empty"):
        split_document("a.pdf", b"")
    with pytest.raises(DocumentError, match="PDF could not be read"):
        split_document("a.pdf", b"%PDF-1.7 not really")
    with pytest.raises(DocumentError, match="no PNG or JPEG"):
        split_document("a.zip", make_zip(["notes.txt"]))


def test_page_text_orders_blocks_drops_running_headers_and_flattens_tables():
    blocks = [
        {"layout_tag": "page-number", "reading_order": 9, "text": "Page 3 of 6"},
        {"layout_tag": "paragraph", "reading_order": 3, "text": "Payment is due in 30 days."},
        {"layout_tag": "header", "reading_order": 1, "text": "ACME Contract"},
        {"layout_tag": "section-title", "reading_order": 2, "text": "Payment terms"},
        {"layout_tag": "table", "reading_order": 4,
         "text": "<table><tr><td>Plan</td><td>Price</td></tr><tr><td>Pro</td><td>&#8377;499</td></tr></table>"},
    ]
    assert page_text(blocks) == "## Payment terms\n\nPayment is due in 30 days.\n\nPlan | Price\nPro | ₹499"
    assert html_table_text("<p>no rows</p>") == "no rows"


def test_chunks_follow_headings_and_keep_page_ranges():
    pages = [
        Page(1, "# Handbook\n\n" + "Intro sentence. " * 20),
        Page(2, "## Refunds\n\nRefunds take seven days.\n\nContact support first."),
        Page(3, "More about refunds continues here."),
    ]
    chunks = chunk_pages(pages, max_chars=400)
    assert chunks[0].heading == "Handbook" and chunks[0].page_start == 1
    refunds = [c for c in chunks if c.heading == "Refunds"]
    assert refunds and refunds[-1].page_end == 3
    assert "Refunds take seven days." in refunds[0].text
    assert [c.seq for c in chunks] == list(range(len(chunks)))
    assert all(len(c.text) <= 400 for c in chunks)


def test_long_paragraphs_split_at_sentences_or_hard_wrap():
    sentence = "This clause explains the warranty in detail. "
    chunks = chunk_pages([Page(1, sentence * 40), Page(2, "x" * 950)], max_chars=300)
    assert all(len(c.text) <= 300 for c in chunks)
    assert sum(c.text.count("warranty") for c in chunks) == 40
    assert "".join(c.text for c in chunks if c.page_start == 2).count("x") == 950
    with pytest.raises(ValueError):
        chunk_pages([], max_chars=50)
    assert chunk_pages([Page(1, "   ")]) == []
