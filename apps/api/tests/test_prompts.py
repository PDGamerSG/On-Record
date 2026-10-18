"""Every prompt that carries outside material tells the model to treat it as material only."""

from __future__ import annotations

import importlib
import pkgutil

import pytest

import wsw_brain
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

# Constants named like prompts that are not model instructions: EmbeddingGemma's task prefixes.
NOT_INSTRUCTIONS = {"wsw_brain.brain.embed.QUERY_PROMPT", "wsw_brain.brain.embed.DOCUMENT_PROMPT"}


def _prompt_constants() -> dict[str, str]:
    """Module-level strings named *PROMPT or *_SYSTEM in every wsw_brain module, by qualified name."""
    found: dict[str, str] = {}
    for info in pkgutil.walk_packages(wsw_brain.__path__, "wsw_brain."):
        module = importlib.import_module(info.name)
        for name, value in vars(module).items():
            if isinstance(value, str) and name.endswith(("PROMPT", "_SYSTEM")):
                found[f"{info.name}.{name}"] = value
    return found


def test_every_prompt_constant_is_guarded_or_exempt() -> None:
    """A new prompt fails here until it is added to PROMPTS (ending with UNTRUSTED_NOTE) or NOT_INSTRUCTIONS."""
    found = _prompt_constants()
    assert "wsw_brain.brain.agent._SYSTEM_PROMPT" in found and NOT_INSTRUCTIONS <= set(found)
    guarded = set(PROMPTS.values())
    unguarded = sorted(
        name for name, value in found.items() if value not in guarded and name not in NOT_INSTRUCTIONS
    )
    assert unguarded == []


@pytest.mark.parametrize("name", sorted(PROMPTS))
def test_prompt_marks_outside_material_as_untrusted(name: str) -> None:
    prompt = PROMPTS[name].rstrip()
    assert prompt.endswith(UNTRUSTED_NOTE)
    assert prompt.count(UNTRUSTED_NOTE) == 1
