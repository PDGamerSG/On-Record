"""Load the web app's two bundled demo meetings into FalkorDB, so document answers can cite them.

    uv run --project apps/api python scripts/seed_demo_meetings.py

Writes meetings, speaker names, utterances (with embeddings from the configured embedder) and summaries.
Re-running replaces the same meetings. Extracted decisions and action items are not written.
"""

from __future__ import annotations

import json
from pathlib import Path

from wsw_brain.brain import get_embedder
from wsw_brain.config import settings
from wsw_brain.contracts import Utterance
from wsw_brain.graph import GraphStore

FIXTURES = Path(__file__).resolve().parents[1] / "apps" / "web" / "src" / "api" / "demo" / "fixtures.json"


def main() -> None:
    config = settings()
    embedder = get_embedder()
    store = GraphStore(config.falkordb_url, config.graph)
    store.ensure_schema(embedder.dim)
    fixtures = json.loads(FIXTURES.read_text())
    try:
        for meeting_id, detail in fixtures["details"].items():
            meeting = detail["meeting"]
            store.delete_meeting(meeting_id)
            store.create_meeting(meeting_id, meeting["title"], "demo", int(meeting["started_at"]))
            utterances = [
                Utterance(meeting_id, int(u["seq"]), u["speaker"], float(u["t_start"]), float(u["t_end"]), u["text"],
                          float(u.get("confidence", 1.0)))
                for u in detail["utterances"]
            ]
            store.write_utterances(utterances, embedder.embed_documents([u.text for u in utterances]))
            for speaker in detail["speakers"]:
                if speaker.get("name"):
                    store.name_speaker(meeting_id, speaker["track"], speaker["name"])
            store.end_meeting(meeting_id, int(meeting.get("ended_at") or meeting["started_at"]),
                              float(meeting.get("duration_s") or 0.0))
            if meeting.get("summary"):
                store.set_meeting_summary(meeting_id, meeting["summary"])
            print(f"seeded {meeting_id}: {len(utterances)} utterances ({embedder.name})")
    finally:
        store.close()


if __name__ == "__main__":
    main()
