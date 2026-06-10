"""
Shared prompt loading utilities.

Load prompts from prompts/*.md files and fill template variables.
All services should use this instead of duplicating _load_prompt.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

PROMPT_DIR = Path(__file__).parents[2] / "prompts"


def load_prompt(name: str) -> str:
    path = PROMPT_DIR / f"{name}.md"
    text = path.read_text(encoding="utf-8")
    match = re.search(r"```\s*\n(.*?)\n```", text, re.DOTALL)
    return match.group(1) if match else text


def render_prompt(template: str, **values: Any) -> str:
    for key, value in values.items():
        template = template.replace("{" + key + "}", str(value or ""))
    return template
