"""Prompt loading and versioning.

Prompts live as Markdown files under `app/prompts/` and are loaded here (never
hardcoded). Each prompt carries a version constant so prompt file names and
versions can be included in trace logs. Prompt changes never bypass the
deterministic guardrails — the policy validator and answer verifier always run.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

_PROMPT_DIR = Path(__file__).resolve().parents[1] / "prompts"

# Prompt file names.
SYSTEM_PROCUREMENT = "system.procurement.md"
INTENT_CLASSIFIER = "intent_classifier.md"
TOOL_PLANNER = "tool_planner.md"
ANSWER_GENERATOR = "answer_generator.md"
ANSWER_VERIFIER = "answer_verifier.md"

# Prompt version constants (bump on any content change; surfaced in traces).
PROMPT_VERSIONS: dict[str, str] = {
    SYSTEM_PROCUREMENT: "v1",
    INTENT_CLASSIFIER: "v1",
    TOOL_PLANNER: "v1",
    ANSWER_GENERATOR: "v1",
    ANSWER_VERIFIER: "v1",
}


@cache
def load_prompt(name: str) -> str:
    """Load a prompt file's text by name."""
    path = _PROMPT_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {name}")
    return path.read_text(encoding="utf-8").strip()


def prompt_version(name: str) -> str:
    """Return the version constant for a prompt file."""
    return PROMPT_VERSIONS.get(name, "unknown")


def prompt_meta() -> list[dict[str, str]]:
    """Return prompt name/version pairs for trace logging."""
    return [{"prompt": name, "version": ver} for name, ver in PROMPT_VERSIONS.items()]
