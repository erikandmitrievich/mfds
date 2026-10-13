#!/usr/bin/env python3
"""ps_extraction.py — a problem-set PDF -> ps_NN.org, via the Anthropic API.

Sends the sheet's source PDF to the model and writes the returned org to
ps_NN.org. The source is ps_NN_source.pdf, or, in a course whose exercises
close each lecture handout, the handout itself; the justfile picks which. Such
a course has no ps_NN/ before its first extraction, so the write creates it.
The system prompt is built from two Org files, each with its #+ header dropped:
math_notation.org inside <math_notation> tags (the repository's math rules,
which the extraction rule delegates to), followed by the ps_extraction rule.

The output file is also where worked solutions live, so the write is guarded:
--force lifts the plain "file exists" refusal, but a file whose ** Solution
carries real work is refused *unconditionally*. Regenerating a solved set is a
manual move (move it aside, or use --stdout to diff by hand). The tool cannot
destroy worked math.

Paths are resolved by the justfile; this script takes concrete paths.
Shared helpers live in extraction_common.py.
Env: ANTHROPIC_API_KEY_MFDS.
"""

from __future__ import annotations

import argparse
import base64
import re
import sys
from pathlib import Path

from extraction_common import (DEFAULT_MODEL, build_system_prompt, call_api,
                               print_usage, reply_text, truncated, unfence)

DEFAULT_MAX_TOKENS = 16384
SOLUTION_RE = re.compile(r"^\*\*\s+Solution\b", re.I)
HEADING_RE = re.compile(r"^\*+\s")


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


def pdf_content(pdf: Path) -> list[dict]:
    """The user turn: the PDF as a document block, then the instruction."""
    data = base64.standard_b64encode(pdf.read_bytes()).decode()
    return [
        {"type": "document",
         "source": {"type": "base64",
                    "media_type": "application/pdf",
                    "data": data}},
        {"type": "text",
         "text": "Process the attached PDF according to the rules."},
    ]


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--pdf", required=True, type=Path,
                    help="ps_NN_source.pdf, or the lecture handout")
    ap.add_argument("--rule", required=True, type=Path, help="ps_extraction rule")
    ap.add_argument("--notation", required=True, type=Path,
                    help="math_notation.org (math rules the extraction rule "
                         "delegates to)")
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

    for label, p in (("source pdf", args.pdf),
                     ("rule file", args.rule),
                     ("notation file", args.notation)):
        if not p.exists():
            print(f"no {label}: {p}", file=sys.stderr)
            return 1

    out_exists = args.out.exists()
    solved = out_exists and has_solution_work(args.out)

    if args.dry_run:
        kib = args.pdf.stat().st_size // 1024
        tag = ("  [HAS SOLUTIONS]" if solved
               else "  [EXISTS]" if out_exists else "")
        print(f"pdf       {args.pdf}  ({kib} KiB)")
        print(f"rule      {args.rule}")
        print(f"notation  {args.notation}")
        print(f"out       {args.out}{tag}")
        print(f"model     {args.model}   max_tokens {args.max_tokens}")
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

    system = build_system_prompt(args.rule, args.notation)
    print(f"extracting {args.pdf.name} -> {args.out.name} [{args.model}] ...",
          file=sys.stderr)
    msg = call_api(pdf_content(args.pdf), system, args.model, args.max_tokens)

    content, fenced = unfence(reply_text(msg))
    print_usage(msg)

    if truncated(msg):
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

    args.out.parent.mkdir(exist_ok=True)
    args.out.write_text(content, encoding="utf-8")
    print(f"wrote {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
