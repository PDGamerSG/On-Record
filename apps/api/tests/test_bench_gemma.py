from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.bench_gemma import run_benchmark


def test_fake_benchmark_writes_schema_and_aggregate(tmp_path: Path) -> None:
    output = tmp_path / "result.json"

    report = run_benchmark(
        ROOT / "benchmarks" / "gemma_smoke.json",
        provider="fake",
        model="gemma4:12b-it-qat",
        output_path=output,
    )

    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved["provider"] == "fake"
    assert saved["model"] == "gemma4:12b-it-qat"
    assert saved["summary"]["total"] == len(saved["cases"])
    assert saved["summary"]["errors"] == 0
    assert report["corpus_version"] == "gemma-smoke-v1"
