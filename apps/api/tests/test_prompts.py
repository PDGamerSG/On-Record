"""Every prompt that carries outside material tells the model to treat it as material only."""

from __future__ import annotations

import pytest

from wsw_brain.brain import agent, extract, summary
from wsw_brain.brain.llm import UNTRUSTED_NOTE
from wsw_brain.documents import answer, vision

PROMPTS = {
    "meeting agent": agent._SYSTEM_PROMPT,
    "meeting extractor": extract.SYSTEM_PROMPT,
    "meeting summaries": summary.SYSTEM_PROMPT,
    "document answers": answer.ANSWER_SYSTEM,
    "document and meeting answers": answer.ANSWER_WITH_MEETINGS_SYSTEM,
    "document summaries": answer.SUMMARY_SYSTEM,
    "image descriptions": vision.VISION_PROMPT,
}


@pytest.mark.parametrize("name", sorted(PROMPTS))
def test_prompt_marks_outside_material_as_untrusted(name: str) -> None:
    prompt = PROMPTS[name].rstrip()
    assert prompt.endswith(UNTRUSTED_NOTE)
    assert prompt.count(UNTRUSTED_NOTE) == 1
