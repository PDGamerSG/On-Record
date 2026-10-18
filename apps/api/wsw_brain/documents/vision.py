"""Gemma 4 image understanding for uploaded pictures: whiteboards, slides, charts and diagrams.

Sarvam Vision reads the text on an image; Gemma 4 31B (via Sarvam) describes what the text alone misses,
such as arrows between boxes, chart trends or which item a note points at. The description is stored
with the page so it can be searched and cited like any other passage.
"""

from __future__ import annotations

import base64

from ..contracts import LLM

MAX_IMAGE_BYTES = 7 * 1024 * 1024  # Sarvam rejects request bodies over 10 MB; base64 adds a third

VISION_PROMPT = """This image was uploaded to a team's meeting notes. It may be a whiteboard photo, a slide,
a chart, a diagram or a scanned page. Describe what it shows that plain text extraction would miss:
structure (boxes, arrows, groupings, tables), chart axes and trends, and any decisions, owners, dates or
numbers it states. Use short plain sentences or "- " bullet points, at most 120 words. Do not invent
details that are not visible."""


def supports_images(llm: LLM | None) -> bool:
    return bool(llm is not None and getattr(llm, "supports_images", False))


async def describe_image(llm: LLM, data: bytes, content_type: str) -> str:
    """Gemma 4's description of an image, or "" for images that are too large to send."""
    if content_type not in ("image/png", "image/jpeg") or len(data) > MAX_IMAGE_BYTES:
        return ""
    uri = f"data:{content_type};base64,{base64.b64encode(data).decode('ascii')}"
    result = await llm.chat(
        [{"role": "user", "content": [
            {"type": "text", "text": VISION_PROMPT},
            {"type": "image_url", "image_url": {"url": uri}},
        ]}],
        temperature=0.2,
        max_tokens=400,
    )
    return result.text.strip()
