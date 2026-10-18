"""Run a repeatable structured-output smoke benchmark against Gemma."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

from pydantic import BaseModel
from wsw_brain.brain.gemma import FakeGemmaClient, GemmaClient


class AnswerPayload(BaseModel):
    answer: str


BENCHMARK_SYSTEM = "Return exactly one JSON object with one string field named answer. No markdown or extra fields."


def _client(provider: str, model: str) -> GemmaClient | FakeGemmaClient:
    if provider == "fake":
        return FakeGemmaClient(model)
    if provider == "ollama":
        return GemmaClient("ollama", model, os.environ.get("WSW_OLLAMA_URL", "http://127.0.0.1:11434"))
    if provider == "gemini":
        key = os.environ.get("GEMINI_API_KEY")
        return GemmaClient("gemini", model, "https://generativelanguage.googleapis.com", key)
    if provider == "openai":
        return GemmaClient("openai", model, os.environ.get("WSW_OPENAI_BASE_URL"), os.environ.get("WSW_OPENAI_API_KEY"))
    raise ValueError(f"unsupported provider: {provider}")


async def _run_case(client: GemmaClient | FakeGemmaClient, case: dict[str, Any]) -> dict[str, Any]:
    started = perf_counter()
    result: dict[str, Any] = {"id": case["id"], "status": "ok", "json_valid": False}
    try:
        messages = [{"role": "system", "content": BENCHMARK_SYSTEM}, *case["messages"]]
        parsed = await client.chat_json(messages, AnswerPayload)
        values = parsed.model_dump()
        expected = case.get("expected") or {}
        matches = sum(values.get(key) == value for key, value in expected.items())
        result.update(
            {
                "json_valid": True,
                "exact_match": bool(expected) and matches == len(expected),
                "field_matches": matches,
                "field_total": len(expected),
            }
        )
    except Exception as exc:  # noqa: BLE001 - the report records per-case failures
        result.update({"status": "error", "error": type(exc).__name__, "message": str(exc)[:200]})
    result["latency_ms"] = round((perf_counter() - started) * 1000, 1)
    return result


async def _run(corpus: dict[str, Any], provider: str, model: str) -> dict[str, Any]:
    client = _client(provider, model)
    cases = [await _run_case(client, case) for case in corpus["cases"]]
    errors = sum(item["status"] == "error" for item in cases)
    valid = sum(item["json_valid"] for item in cases)
    exact = sum(item.get("exact_match", False) for item in cases)
    fields = sum(item.get("field_matches", 0) for item in cases)
    field_total = sum(item.get("field_total", 0) for item in cases)
    return {
        "corpus_version": corpus["corpus_version"],
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "python": platform.python_version(),
        "provider": provider,
        "model": model,
        "cases": cases,
        "summary": {
            "total": len(cases),
            "errors": errors,
            "json_valid": valid,
            "json_valid_rate": round(valid / len(cases), 3) if cases else 0.0,
            "exact_matches": exact,
            "field_matches": fields,
            "field_total": field_total,
            "field_match_rate": round(fields / field_total, 3) if field_total else 0.0,
        },
    }


def run_benchmark(corpus_path: Path, *, provider: str, model: str, output_path: Path) -> dict[str, Any]:
    """Run the corpus and persist a JSON report."""
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    if not isinstance(corpus, dict) or not corpus.get("cases"):
        raise ValueError("benchmark corpus must contain a non-empty cases array")
    report = asyncio.run(_run(corpus, provider, model))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=("fake", "ollama", "gemini", "openai"), default="fake")
    parser.add_argument("--model", default=None)
    parser.add_argument("--corpus", type=Path, default=Path("benchmarks/gemma_smoke.json"))
    parser.add_argument("--out", type=Path, default=Path("benchmarks/results/latest.json"))
    args = parser.parse_args(argv)
    defaults = {
        "fake": "gemma4:12b-it-qat",
        "ollama": "gemma4:12b-it-qat",
        "gemini": "gemma-4-26b-a4b-it",
        "openai": "gemma-4-26b-a4b-it",
    }
    try:
        report = run_benchmark(args.corpus, provider=args.provider, model=args.model or defaults[args.provider], output_path=args.out)
    except (OSError, ValueError) as exc:
        print(f"benchmark configuration error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report["summary"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
