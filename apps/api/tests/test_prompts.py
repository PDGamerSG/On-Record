"""Every prompt that carries outside material tells the model to treat it as material only."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import wsw_brain
from wsw_brain.brain import agent, extract, summary
from wsw_brain.brain.llm import UNTRUSTED_NOTE
from wsw_brain.documents import answer, vision

# Keyed by where each prompt is defined, so the discovery test below can tell them apart by name.
PROMPTS = {
    "wsw_brain.brain.agent._SYSTEM_PROMPT": agent._SYSTEM_PROMPT,
    "wsw_brain.brain.extract.SYSTEM_PROMPT": extract.SYSTEM_PROMPT,
    "wsw_brain.brain.summary.SYSTEM_PROMPT": summary.SYSTEM_PROMPT,
    "wsw_brain.documents.answer.ANSWER_SYSTEM": answer.ANSWER_SYSTEM,
    "wsw_brain.documents.answer.ANSWER_WITH_MEETINGS_SYSTEM": answer.ANSWER_WITH_MEETINGS_SYSTEM,
    "wsw_brain.documents.answer.SUMMARY_SYSTEM": answer.SUMMARY_SYSTEM,
    "wsw_brain.documents.vision.VISION_PROMPT": vision.VISION_PROMPT,
}

# Constants named like prompts that are not model instructions: EmbeddingGemma's task prefixes.
NOT_INSTRUCTIONS = {"wsw_brain.brain.embed.QUERY_PROMPT", "wsw_brain.brain.embed.DOCUMENT_PROMPT"}
PACKAGE = Path(wsw_brain.__file__).parent


def _prompt_constants() -> set[str]:
    """Qualified names assigned at module level to *PROMPT or *_SYSTEM in the wsw_brain sources.

    The files are parsed, not imported, so no module runs and a re-exported prompt is not counted twice.
    """
    names: set[str] = set()
    for path in sorted(PACKAGE.rglob("*.py")):
        parts = path.relative_to(PACKAGE).with_suffix("").parts
        module = ".".join(["wsw_brain", *parts]).removesuffix(".__init__")
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, ast.AnnAssign | ast.AugAssign):
                targets = [node.target]
            else:
                continue
            names.update(
                f"{module}.{target.id}"
                for target in targets
                if isinstance(target, ast.Name) and target.id.endswith(("PROMPT", "_SYSTEM"))
            )
    return names


def test_every_prompt_constant_is_guarded_or_exempt() -> None:
    """A new prompt fails here until it is added to PROMPTS (ending with UNTRUSTED_NOTE) or NOT_INSTRUCTIONS."""
    found = _prompt_constants()
    assert set(PROMPTS) <= found and NOT_INSTRUCTIONS <= found  # neither list names a prompt that is gone
    assert sorted(found - set(PROMPTS) - NOT_INSTRUCTIONS) == []


@pytest.mark.parametrize("name", sorted(PROMPTS))
def test_prompt_marks_outside_material_as_untrusted(name: str) -> None:
    prompt = PROMPTS[name].rstrip()
    assert prompt.endswith(UNTRUSTED_NOTE)
    assert prompt.count(UNTRUSTED_NOTE) == 1
