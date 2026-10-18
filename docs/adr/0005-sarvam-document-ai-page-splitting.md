# ADR-0005: Sarvam Document AI with 10-page splitting

## Context

Teams record decisions in contracts, specs and policies as well as in meetings (README.md:262). Uploaded PDFs, page-image ZIPs and photos must become searchable text with correct page numbers. Sarvam Document AI "rejects PDFs and ZIPs with more pages than" 10 (apps/api/wsw_brain/documents/split.py:22).

## Decision

Documents are digitised by Sarvam Document AI (Sarvam Vision) through a job client: create a job, poll its status, fetch the download URL and read per-page JSON from the ZIP (apps/api/wsw_brain/documents/sarvam.py:1-5). `split_document` cuts longer files into consecutive parts of at most 10 pages and records which source pages each part covers (apps/api/wsw_brain/documents/split.py:1-6). Parts are digitised in parallel, and page numbers are shifted back to the original document so a citation such as "p. 14" points at the right page (apps/api/wsw_brain/documents/ingest.py:1-4). Limits are settings: 10 pages per part, 100 pages, 25 MB, 3 parts in parallel (apps/api/wsw_brain/config.py:45-49).

## Status

Accepted (retroactive)

## Consequences

Positive:

- Documents of up to 100 pages can be processed despite the per-job limit.
- Parallel parts shorten ingestion; a semaphore bounds the concurrency (apps/api/wsw_brain/documents/ingest.py:108).
- Tables become `cell | cell` rows and running headers are dropped (README.md:265).

Negative:

- Document text is sent to an external service, and ingestion needs `SARVAM_API_KEY` (README.md:272).
- Page-offset bookkeeping is extra code that must stay correct.
- The web app on `main` has no Documents page yet (docs/ARCHITECTURE.md:57).

## Alternatives

Not recorded in the repository.

## Sources

- apps/api/wsw_brain/documents/split.py:1-22
- apps/api/wsw_brain/documents/sarvam.py:1-5
- apps/api/wsw_brain/documents/ingest.py:1-4
- apps/api/wsw_brain/documents/ingest.py:108
- apps/api/wsw_brain/config.py:45-49
- README.md:262-272
- docs/ARCHITECTURE.md:57
