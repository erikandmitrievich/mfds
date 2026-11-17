#!/usr/bin/env python3
"""lec_transcription.py — a lecture handout PDF -> lec_NN.org, via the Anthropic API.

Sends the course's 01_material/_lec_NN_source.pdf to the model and writes the
returned transcription to 01_material/lec_NN.org. The transcription mirrors the
handout's own sections; the exercise section is left out (ps_extraction.py
turns it into ps_NN.org). A companion notebook (_lec_NN_source.ipynb) is not
read.

The system prompt is built from two Org files, each with its #+ header dropped:
math_notation.org inside <math_notation> tags, followed by the transcription
rule.

The reply opens with a "#+title: ..." line (the rule's contract). The script
takes the title from it and writes the repository's standard file header
around the body; a reply without that line falls back to "Lec NN".

Checks, in code rather than in the prompt:
  before the call  the pdf, rule and notation exist; out does not exist
                   (--force lifts this)
  after the call   a truncated reply is not written (it goes to stdout); a
                   missing fence or title line only warns. The [?: ...],
                   [ILLEGIBLE: ...] and [GRAPHIC: ...] markers are counted, so
                   you know what to review.

Paths are resolved by the justfile; this script takes concrete paths.
Shared helpers live in extraction_common.py.
Env: ANTHROPIC_API_KEY_MFDS.
"""

from __future__ import annotations

import argparse
import base64
import re
import sys
from datetime import datetime
from pathlib import Path

from extraction_common import (DEFAULT_MODEL, build_system_prompt, call_api,
                               print_usage, reply_text, truncated, unfence)

DEFAULT_MAX_TOKENS = 32000

TITLE_RE = re.compile(r"^\s*#\+title:\s*(.+?)\s*$", re.I)
MARKERS = {"uncertain": re.compile(r"\[\?:"),
           "illegible": re.compile(r"\[ILLEGIBLE:"),
           "graphic":   re.compile(r"\[GRAPHIC:")}

HEADER = """\
#+title: {title}
#+author: Erik An
#+email: obluda2173@gmail.com
#+date: <{date}>
#+lastmod: <{date} {time}>
#+latex: \\newpage
#+latex_header: \\setlength{{\\parindent}}{{0pt}}
#+latex_header: \\setlength{{\\parskip}}{{1em}}
#+latex_header: \\usepackage{{amsmath}}
#+latex_header: \\usepackage{{amssymb}}
#+latex_header: \\usepackage{{mathtools}}
#+latex_header: \\usepackage{{amsthm}}
#+latex_header: \\usepackage[margin=1in]{{geometry}}
#+options: num:t tags:nil
#+property: header-args :eval never-export
#+startup: overview inlineimages
#+columns: %50ITEM(Item) %8LECTURE_REF(Lecture) %34CUSTOM_ID(ID)
"""


def pdf_content(pdf: Path) -> list[dict]:
    """The user turn: the PDF as a document block, then the instruction."""
    data = base64.standard_b64encode(pdf.read_bytes()).decode()
    return [
        {"type": "document",
         "source": {"type": "base64",
                    "media_type": "application/pdf",
                    "data": data}},
        {"type": "text",
         "text": "Transcribe the attached lecture handout according to the "
                 "rules."},
    ]


def split_title(org: str) -> tuple[str | None, str]:
    """Take the leading #+title: line off the reply; return (title, body)."""
    lines = org.lstrip("\n").splitlines()
    if lines and (m := TITLE_RE.match(lines[0])):
        return m.group(1), "\n".join(lines[1:]).strip() + "\n"
    return None, org.strip() + "\n"


def default_title(out: Path) -> str:
    """lec_03.org -> "Lec 03"; lec_02-03.org -> "Lec 02-03"."""
    return out.stem.replace("lec_", "Lec ", 1)


def report_markers(body: str) -> None:
    counts = {k: len(rx.findall(body)) for k, rx in MARKERS.items()}
    print("markers: " + "  ".join(f"{k} {n}" for k, n in counts.items()),
          file=sys.stderr)
    if counts["uncertain"] or counts["illegible"]:
        print("review: grep -n '\\[?:\\|\\[ILLEGIBLE:' on the output",
              file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--pdf", required=True, type=Path,
                    help="the lecture handout, _lec_NN_source.pdf")
    ap.add_argument("--rule", required=True, type=Path,
                    help="lec_transcription rule")
    ap.add_argument("--notation", required=True, type=Path,
                    help="math_notation.org (math rules the rule delegates to)")
    ap.add_argument("--out", required=True, type=Path, help="lec_NN.org target")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    ap.add_argument("--force", action="store_true",
                    help="overwrite an existing out")
    ap.add_argument("--stdout", action="store_true",
                    help="print the file instead of writing --out "
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

    if args.dry_run:
        kib = args.pdf.stat().st_size // 1024
        print(f"pdf       {args.pdf}  ({kib} KiB)")
        print(f"rule      {args.rule}")
        print(f"notation  {args.notation}")
        print(f"out       {args.out}{'  [EXISTS]' if out_exists else ''}")
        print(f"model     {args.model}   max_tokens {args.max_tokens}")
        if out_exists and not args.force:
            print("would REFUSE: out exists (pass --force)")
        else:
            print("would write out")
        return 0

    if not args.stdout and out_exists and not args.force:
        print(f"refusing: {args.out} exists (pass --force, or --stdout to "
              f"diff by hand)", file=sys.stderr)
        return 1

    system = build_system_prompt(args.rule, args.notation)
    print(f"transcribing {args.pdf.name} -> {args.out.name} [{args.model}] ...",
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

    title, body = split_title(content)
    if title is None:
        title = default_title(args.out)
        print(f"WARNING: no #+title: line in the reply; using '{title}'.",
              file=sys.stderr)
    report_markers(body)

    now = datetime.now()
    text = HEADER.format(title=title, date=f"{now:%Y-%m-%d}",
                         time=f"{now:%H:%M}") + "\n" + body

    if args.stdout:
        sys.stdout.write(text)
        return 0

    args.out.write_text(text, encoding="utf-8")
    print(f"wrote {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
