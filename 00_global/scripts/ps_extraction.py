#!/usr/bin/env python3
"""extract_ps.py — a problem-set PDF -> ps_NN.org, via the Anthropic API.

Sends ps_NN_source.pdf to the model with the ps_extraction rule as the system
prompt and writes the returned org to ps_NN.org.

The output file is also where worked solutions live, so the write is guarded:
--force lifts the plain "file exists" refusal, but a file whose ** Solution
carries real work is refused *unconditionally*. Regenerating a solved set is a
manual move (move it aside, or use --stdout to diff by hand). The tool cannot
destroy worked math.

Paths are resolved by the justfile; this script takes concrete paths.
Env: ANTHROPIC_API_KEY.
"""

from __future__ import annotations

import argparse
import base64
import re
import os
import sys
from pathlib import Path

DEFAULT_MODEL = "claude-opus-4-8"
DEFAULT_MAX_TOKENS = 16384

# ```org ... ``` — the rule wraps its output in one fenced block.
FENCE_RE = re.compile(r"^\s*```(?:org)?\s*\n(.*?)\n```\s*$", re.S)
SOLUTION_RE = re.compile(r"^\*\*\s+Solution\b", re.I)
HEADING_RE = re.compile(r"^\*+\s")


def load_system_prompt(rule_path: Path) -> str:
    """The rule file from its first Org heading on (drop the #+ metadata head)."""
    lines = rule_path.read_text(encoding="utf-8").splitlines()
    for i, ln in enumerate(lines):
        if ln.startswith("* "):
            return "\n".join(lines[i:]).strip()
    return "\n".join(lines).strip()


def has_solution_work(path: Path) -> bool:
    """True if any ** Solution section holds a non-blank, non-heading line.

    Empty scaffolds (*** (a) with nothing under them) are the extraction format
    and do NOT count. A Julia #+begin_src line under Solution does count.
    """
    in_sol = False
    for ln in path.read_text(encoding="utf-8").splitlines():
        if SOLUTION_RE.match(ln):
            in_sol = True
            continue
        if HEADING_RE.match(ln):
            # *** sub-headings belong to the Solution; ** / * siblings end it.
            if not ln.startswith("*** "):
                in_sol = False
            continue
        if in_sol and ln.strip():
            return True
    return False


def unfence(text: str) -> tuple[str, bool]:
    """Strip the ```org fence. Second value is False if no closing fence was
    found (a truncation smell; stop_reason is the authoritative check)."""
    m = FENCE_RE.match(text.strip())
    if m:
        return m.group(1).strip() + "\n", True
    return text.strip() + "\n", False


def call_api(pdf: Path, system: str, model: str, max_tokens: int):
    try:
        from anthropic import Anthropic
    except ImportError:
        sys.exit("anthropic SDK not installed: pip install anthropic")

    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY_MFDS"])
    data = base64.standard_b64encode(pdf.read_bytes()).decode()
    return client.messages.create(
        model=model,
        max_tokens=max_tokens,
        # temperature=0,
        system=system,
        messages=[{
            "role": "user",
            "content": [
                {"type": "document",
                 "source": {"type": "base64",
                            "media_type": "application/pdf",
                            "data": data}},
                {"type": "text",
                 "text": "Process the attached PDF according to the rules."},
            ],
        }],
    )


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--pdf", required=True, type=Path, help="ps_NN_source.pdf")
    ap.add_argument("--rule", required=True, type=Path, help="ps_extraction rule")
    ap.add_argument("--out", required=True, type=Path, help="ps_NN.org target")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    ap.add_argument("--force", action="store_true",
                    help="overwrite an existing out that has NO solution work")
    ap.add_argument("--stdout", action="store_true",
                    help="print the extraction instead of writing --out "
                         "(bypasses the write guard)")
    ap.add_argument("--dry-run", action="store_true",
                    help="resolve paths and report; make no API call")
    args = ap.parse_args()

    if not args.pdf.exists():
        print(f"no source pdf: {args.pdf}", file=sys.stderr)
        return 1
    if not args.rule.exists():
        print(f"no rule file: {args.rule}", file=sys.stderr)
        return 1

    out_exists = args.out.exists()
    solved = out_exists and has_solution_work(args.out)

    if args.dry_run:
        kib = args.pdf.stat().st_size // 1024
        tag = ("  [HAS SOLUTIONS]" if solved
               else "  [EXISTS]" if out_exists else "")
        print(f"pdf    {args.pdf}  ({kib} KiB)")
        print(f"rule   {args.rule}")
        print(f"out    {args.out}{tag}")
        print(f"model  {args.model}   max_tokens {args.max_tokens}")
        if solved:
            print("would REFUSE: out has solution work (not overwritable)")
        elif out_exists and not args.force:
            print("would REFUSE: out exists (pass --force)")
        else:
            print("would write out")
        return 0

    # write guard — irrelevant when only printing
    if not args.stdout:
        if solved:
            print(f"refusing: {args.out} contains solution work; "
                  f"move it aside to regenerate", file=sys.stderr)
            return 1
        if out_exists and not args.force:
            print(f"refusing: {args.out} exists (pass --force)", file=sys.stderr)
            return 1

    system = load_system_prompt(args.rule)
    print(f"extracting {args.pdf.name} -> {args.out.name} [{args.model}] ...",
          file=sys.stderr)
    msg = call_api(args.pdf, system, args.model, args.max_tokens)

    text = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
    content, fenced = unfence(text)

    usage = getattr(msg, "usage", None)
    if usage:
        print(f"tokens: in {usage.input_tokens}  out {usage.output_tokens}",
              file=sys.stderr)

    if getattr(msg, "stop_reason", None) == "max_tokens":
        print("WARNING: hit max_tokens — output truncated. Re-run with a "
              "larger --max-tokens. Not writing; dumping to stdout.",
              file=sys.stderr)
        sys.stdout.write(content)
        return 1
    if not fenced:
        print("WARNING: no ```org fence found; using raw model output.",
              file=sys.stderr)

    if args.stdout:
        sys.stdout.write(content)
        return 0

    args.out.write_text(content, encoding="utf-8")
    print(f"wrote {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
