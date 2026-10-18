"""Build the web UI's offline demo data from scripted Kitepost meetings.

Usage (from apps/web):
    python3 scripts/build_demo_fixtures.py --source <path to the demo directory>

Writes src/api/demo/fixtures.json and public/demo/audio/*.m4a (needs ffmpeg for the audio).
The transcript timings come from the ground-truth files written during synthesis, so the
demo transcript is the script itself, not listener output.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

IST = timezone(timedelta(hours=5, minutes=30))
WEB = Path(__file__).resolve().parent.parent

PEOPLE = {
    "Priya": {"colour": 0, "role": "Head of Product"},
    "Rahul": {"colour": 1, "role": "Finance Manager"},
    "Meera": {"colour": 2, "role": "Sales Lead"},
    "Arjun": {"colour": 3, "role": "Engineering Lead"},
}

MEETINGS = [
    {
        "key": "01-pricing-review",
        "id": "demo-pricing-review",
        "started": datetime(2026, 10, 13, 11, 0, tzinfo=IST),
        "summary": (
            "Kitepost locked self-serve pricing. Starter is 4,999 rupees a month with 1,500 shipments and 4 rupees "
            "overage, after Meera pushed for 3,999 and Rahul held the margin line. Annual billing gets 15 percent off, "
            "reviewed after 90 days. Self-serve launches Monday, November 2, pending GST registration."
        ),
        "decisions": [
            {"text": "Starter tier at 4,999 rupees a month with 1,500 shipments included and 4 rupees per extra shipment", "by": "Priya", "evidence": [12, 15]},
            {"text": "Growth stays at 14,999 rupees for 10,000 shipments; Monsoon Apparel is handled as an Enterprise deal", "by": "Priya", "evidence": [17, 19]},
            {"text": "Annual plans get a 15 percent discount, not 20, reviewed after 90 days of data", "by": "Priya", "evidence": [28, 29]},
            {"text": "Self-serve launches on Monday, November 2", "by": "Priya", "evidence": [35, 39]},
        ],
        "actions": [
            {"owner": "Meera", "text": "Take Monsoon Apparel through the Enterprise proposal", "due": "next week", "evidence": [20]},
            {"owner": "Arjun", "text": "Ship the usage meter, on staging Thursday night, with a warning banner at 90 percent of the plan limit", "due": "Friday", "evidence": [31, 32]},
            {"owner": "Meera", "text": "Send the revised pricing deck to Saffron Basket before their renewal call", "due": "Thursday", "evidence": [33], "done_in": "02-launch-sync"},
            {"owner": "Rahul", "text": "Set up monthly and annual Starter and Growth plans in Razorpay", "due": "Wednesday", "evidence": [34]},
            {"owner": "Priya", "text": "Draft the pricing page and the FAQ, including worked overage examples", "due": "Monday", "evidence": [37]},
            {"owner": "Rahul", "text": "Confirm the GST registration either way", "due": "next Tuesday", "evidence": [41, 42]},
        ],
    },
    {
        "key": "02-launch-sync",
        "id": "demo-launch-sync",
        "started": datetime(2026, 10, 15, 16, 30, tzinfo=IST),
        "summary": (
            "Trackwise cut its small-shipper plan to 3,499, and trial accounts pushed back on price. Starter moves to "
            "3,999 with 1,000 shipments, replacing Tuesday's decision; Rahul's numbers put the margin at 55 percent. "
            "The annual discount and the November 2 launch both hold."
        ),
        "decisions": [
            {"text": "Starter tier moves from 4,999 to 3,999 rupees a month with 1,000 shipments included; overage stays at 4 rupees", "by": "Priya", "evidence": [12, 13], "supersedes": 0},
            {"text": "Annual discount stays at 15 percent", "by": "Rahul", "evidence": [15, 16]},
            {"text": "The self-serve launch on November 2 still holds", "by": "Rahul", "evidence": [24, 25]},
        ],
        "actions": [
            {"owner": "Rahul", "text": "Update the Starter plan in Razorpay to 3,999 with the 1,000-shipment limit", "due": "Monday", "evidence": [17]},
            {"owner": "Priya", "text": "Message Arjun so the usage meter warns at 900 shipments", "due": "today", "evidence": [22]},
            {"owner": "Meera", "text": "Email Saffron Basket and the two trial accounts the new Starter price", "due": "tomorrow morning", "evidence": [23]},
        ],
    },
]

TOPICS = {
    "Starter tier": ["starter"],
    "Overage": ["overage", "per extra shipment", "per shipment"],
    "Annual discount": ["annual"],
    "Usage meter": ["usage meter", "meter"],
    "Launch date": ["launch", "november"],
    "Margin": ["margin"],
    "GST registration": ["gst", "tax registration"],
    "Pricing page": ["pricing page", "faq"],
    "Growth tier": ["growth"],
}

ENTITIES = {
    "Kitepost": ("org", ["kitepost"]),
    "Trackwise": ("competitor", ["trackwise"]),
    "Saffron Basket": ("customer", ["saffron basket"]),
    "Monsoon Apparel": ("customer", ["monsoon"]),
    "Razorpay": ("vendor", ["razorpay"]),
    "WhatsApp": ("product", ["whatsapp"]),
}


def epoch_ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def mentions(text: str, keys: list[str]) -> bool:
    low = text.lower()
    return any(k in low for k in keys)


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def build(source: Path) -> dict:
    meetings, details = [], {}
    decision_ids: dict[tuple[str, int], str] = {}
    action_index: dict[str, dict] = {}
    started_by_key = {m["key"]: m["started"] for m in MEETINGS}

    for spec in MEETINGS:
        script = json.loads((source / "meetings" / f"{spec['key']}.json").read_text())
        truth = json.loads((source / "meetings" / f"{spec['key']}.truth.json").read_text())
        mid = spec["id"]
        started = spec["started"]
        duration = round(float(truth["duration_s"]), 2)

        order: list[str] = []
        for t in truth["turns"]:
            if t["speaker"] not in order:
                order.append(t["speaker"])
        track_of = {name: f"S{i + 1}" for i, name in enumerate(order)}

        utterances = []
        for t in truth["turns"]:
            utterances.append(
                {
                    "id": f"u-{mid}-{t['seq']:03d}",
                    "meeting_id": mid,
                    "seq": t["seq"],
                    "speaker": track_of[t["speaker"]],
                    "speaker_name": t["speaker"],
                    "t_start": round(t["t_start"], 2),
                    "t_end": round(t["t_end"], 2),
                    "text": t["text"],
                    "confidence": round(0.93 + (zlib.crc32(t["text"].encode()) % 60) / 1000, 3),
                }
            )
        uid = {u["seq"]: u["id"] for u in utterances}
        t_of = {u["seq"]: u["t_start"] for u in utterances}

        speakers = []
        for name in order:
            mine = [u for u in utterances if u["speaker_name"] == name]
            speakers.append(
                {
                    "track": track_of[name],
                    "label": f"Speaker {track_of[name][1:]}",
                    "name": name,
                    "person_id": f"p-{slug(name)}",
                    "color_idx": PEOPLE[name]["colour"],
                    "utterance_count": len(mine),
                    "talk_time_s": round(sum(u["t_end"] - u["t_start"] for u in mine), 1),
                }
            )

        decisions = []
        for i, d in enumerate(spec["decisions"]):
            did = f"d-{mid}-{i + 1}"
            decision_ids[(spec["key"], i)] = did
            decisions.append(
                {
                    "id": did,
                    "meeting_id": mid,
                    "text": d["text"],
                    "status": "active",
                    "made_at": t_of[d["evidence"][-1]],
                    "proposed_by": d["by"],
                    "evidence": [uid[s] for s in d["evidence"]],
                    "superseded_by": None,
                    "supersedes": None,
                    "_supersedes_index": d.get("supersedes"),
                }
            )

        actions = []
        for i, a in enumerate(spec["actions"]):
            aid = f"a-{mid}-{i + 1}"
            item = {
                "id": aid,
                "meeting_id": mid,
                "meeting_title": script["title"],
                "text": a["text"],
                "owner": a["owner"],
                "owner_track": track_of[a["owner"]],
                "due": a["due"],
                "status": "open",
                "created_at": epoch_ms(started + timedelta(seconds=t_of[a["evidence"][-1]])),
                "done_at": None,
                "evidence": [uid[s] for s in a["evidence"]],
            }
            if a.get("done_in"):
                item["status"] = "done"
                item["done_at"] = epoch_ms(started_by_key[a["done_in"]] + timedelta(seconds=16))
            actions.append(item)
            action_index[aid] = item

        topics = []
        for name, keys in TOPICS.items():
            n = sum(1 for u in utterances if mentions(u["text"], keys))
            if n:
                topics.append({"id": f"t-{slug(name)}", "name": name, "mentions": n})
        topics.sort(key=lambda t: -t["mentions"])

        entities = []
        for name, (kind, keys) in ENTITIES.items():
            hits = [u["id"] for u in utterances if mentions(u["text"], keys)]
            if hits:
                entities.append({"id": f"e-{slug(name)}", "name": name, "kind": kind, "utterances": hits})

        topic_links = []
        for name, keys in TOPICS.items():
            for u in utterances:
                if mentions(u["text"], keys):
                    topic_links.append([u["id"], f"t-{slug(name)}"])

        summary = {
            "id": mid,
            "title": script["title"],
            "status": "ended",
            "source": "demo",
            "started_at": epoch_ms(started),
            "ended_at": epoch_ms(started + timedelta(seconds=duration)),
            "duration_s": duration,
            "utterance_count": len(utterances),
            "speaker_count": len(speakers),
            "has_audio": True,
            "summary": spec["summary"],
        }
        meetings.append(summary)
        details[mid] = {
            "meeting": summary,
            "speakers": speakers,
            "utterances": utterances,
            "decisions": decisions,
            "action_items": actions,
            "topics": topics,
            "entities": entities,
            "topic_links": topic_links,
            "audio": f"/demo/audio/{spec['key']}.m4a",
        }

    # Supersession: launch sync's Starter decision replaces the pricing review's.
    for spec in MEETINGS:
        for d in details[spec["id"]]["decisions"]:
            idx = d.pop("_supersedes_index")
            if idx is None:
                continue
            old_id = decision_ids[(MEETINGS[0]["key"], idx)]
            d["supersedes"] = old_id
            for old in details[MEETINGS[0]["id"]]["decisions"]:
                if old["id"] == old_id:
                    old["status"] = "superseded"
                    old["superseded_by"] = d["id"]

    people = []
    for name, info in PEOPLE.items():
        pid = f"p-{slug(name)}"
        n_meetings = utt = 0
        talk = 0.0
        for d in details.values():
            sp = [s for s in d["speakers"] if s["name"] == name]
            if sp:
                n_meetings += 1
                utt += sp[0]["utterance_count"]
                talk += sp[0]["talk_time_s"]
        open_items = sum(1 for a in action_index.values() if a["owner"] == name and a["status"] == "open")
        people.append(
            {
                "id": pid,
                "name": name,
                "role": info["role"],
                "meetings": n_meetings,
                "utterances": utt,
                "talk_time_s": round(talk, 1),
                "open_items": open_items,
            }
        )

    meetings.sort(key=lambda m: -m["started_at"])
    return {"meetings": meetings, "details": details, "people": people}


def encode_audio(source: Path) -> None:
    out = WEB / "public" / "demo" / "audio"
    out.mkdir(parents=True, exist_ok=True)
    if not shutil.which("ffmpeg"):
        print("ffmpeg not found; skipping audio")
        return
    for spec in MEETINGS:
        src = source / "audio" / f"{spec['key']}.ogg"
        dst = out / f"{spec['key']}.m4a"
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-ac", "1", "-c:a", "aac", "-b:a", "48k", str(dst)],
            check=True,
        )
        print(f"wrote {dst.relative_to(WEB)} ({dst.stat().st_size // 1024} KB)")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--source", type=Path, required=True, help="the demo directory")
    p.add_argument("--no-audio", action="store_true")
    args = p.parse_args()
    data = build(args.source)
    out = WEB / "src" / "api" / "demo" / "fixtures.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
    print(f"wrote {out.relative_to(WEB)}")
    if not args.no_audio:
        encode_audio(args.source)


if __name__ == "__main__":
    main()
