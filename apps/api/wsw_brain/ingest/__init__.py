"""Live ingest: writes listener utterances to the graph, runs extraction and summaries, publishes events."""

from .pipeline import IngestPipeline

__all__ = ["IngestPipeline"]
