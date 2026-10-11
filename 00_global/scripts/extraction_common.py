#!/usr/bin/env python3
"""extraction_common.py — what the extraction scripts share.

ps_extraction.py (problem-set PDF -> ps_NN.org) and material_extraction.py
(screenshots -> a course's staging file) differ in their input and in where the
output goes. They share how the system prompt is built, how the API is called,
and how the fenced reply is unwrapped. Nothing runs from this file.

Env: ANTHROPIC_API_KEY_MFDS.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

DEFAULT_MODEL = "claude-opus-4-8"
API_KEY_ENV = "ANTHROPIC_API_KEY_MFDS"

# ```org ... ``` — every extraction rule wraps its output in one fenced block.
FENCE_RE = re.compile(r"^\s*```(?:org)?\s*\n(.*?)\n```\s*$", re.S)


def org_body(path: Path) -> str:
    """An Org file from its first heading on (drop the #+ metadata head)."""
    lines = path.read_text(encoding="utf-8").splitlines()
    for i, ln in enumerate(lines):
        if ln.startswith("* "):
            return "\n".join(lines[i:]).strip()
    return "\n".join(lines).strip()


def build_system_prompt(rule_path: Path, notation_path: Path) -> str:
    """Notation first, extraction rule second.

    The notation is reference material, so it goes above the instructions, and
    the rule's closing BEGIN EXTRACTION stays the last thing in the prompt. The
    rule refers to the notation by its tag, not by position.
    """
    notation = org_body(notation_path)
    rule = org_body(rule_path)
    return f"<math_notation>\n{notation}\n</math_notation>\n\n{rule}"


def unfence(text: str) -> tuple[str, bool]:
    """Strip the ```org fence. Second value is False if no closing fence was
    found (a truncation smell; stop_reason is the authoritative check)."""
    m = FENCE_RE.match(text.strip())
    if m:
        return m.group(1).strip() + "\n", True
    return text.strip() + "\n", False


def call_api(content: list[dict], system: str, model: str, max_tokens: int):
    """One user turn with the given content blocks; returns the final Message.

    Streamed: the SDK refuses a non-streaming request whose max_tokens implies
    a long response, and a streamed request returns the same Message.
    """
    try:
        from anthropic import Anthropic
    except ImportError:
        sys.exit("anthropic SDK not installed: pip install anthropic")

    key = os.environ.get(API_KEY_ENV)
    if not key:
        sys.exit(f"{API_KEY_ENV} is not set")

    client = Anthropic(api_key=key)
    with client.messages.stream(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": content}],
    ) as stream:
        return stream.get_final_message()


def reply_text(msg) -> str:
    """The text blocks of a Message, concatenated."""
    return "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")


def truncated(msg) -> bool:
    return getattr(msg, "stop_reason", None) == "max_tokens"


def print_usage(msg) -> None:
    usage = getattr(msg, "usage", None)
    if usage:
        print(f"tokens: in {usage.input_tokens}  out {usage.output_tokens}",
              file=sys.stderr)
