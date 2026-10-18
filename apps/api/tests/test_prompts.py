"""Every prompt that carries outside material tells the model to treat it as material only."""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

import wsw_brain
from wsw_brain.brain.llm import UNTRUSTED_NOTE

# Prompts that carry outside material, by where they are defined. Their values are looked up from those
# modules, so each name is checked against the prompt it names.
PROMPTS = {
    "wsw_brain.brain.agent._SYSTEM_PROMPT",
    "wsw_brain.brain.extract.SYSTEM_PROMPT",
    "wsw_brain.brain.summary.SYSTEM_PROMPT",
    "wsw_brain.documents.answer.ANSWER_SYSTEM",
    "wsw_brain.documents.answer.ANSWER_WITH_MEETINGS_SYSTEM",
    "wsw_brain.documents.answer.SUMMARY_SYSTEM",
    "wsw_brain.documents.vision.VISION_PROMPT",
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


def _value(qualified: str) -> str:
    module, _, name = qualified.rpartition(".")
    return getattr(importlib.import_module(module), name)


def test_every_prompt_constant_is_guarded_or_exempt() -> None:
    """A new prompt fails here until it is listed in PROMPTS, where the test below checks that it ends with
    UNTRUSTED_NOTE, or in NOT_INSTRUCTIONS."""
    found = _prompt_constants()
    assert PROMPTS <= found and NOT_INSTRUCTIONS <= found  # neither list names a prompt that is gone
    assert sorted(found - PROMPTS - NOT_INSTRUCTIONS) == []


@pytest.mark.parametrize("name", sorted(PROMPTS))
def test_prompt_marks_outside_material_as_untrusted(name: str) -> None:
    prompt = _value(name).rstrip()
    assert prompt.endswith(UNTRUSTED_NOTE)
    assert prompt.count(UNTRUSTED_NOTE) == 1
