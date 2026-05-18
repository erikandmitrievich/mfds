#!/usr/bin/env python3
"""Migrate *Proof.* markers to #+begin_proof ... #+end_proof blocks in org files.

Usage:
    python3 migrate_proofs.py FILE [FILE ...]

The script:
  1. Strips standalone $\\square$ lines (amsthm adds its own QED inside the
     proof environment, so manual ones would double up).
  2. Replaces each "*Proof.*" line (with its following blank line) with
     "#+begin_proof".
  3. Inserts "#+end_proof" immediately before the next "** Questions" or
     "* " heading (or at EOF if neither exists).

Idempotent: running it twice on the same file produces no further changes.
"""

import re
import sys
from pathlib import Path

PROOF_START = re.compile(r'^\*Proof\.\*[ \t]*\n(?:[ \t]*\n)?', re.MULTILINE)
SQUARE_LINE = re.compile(r'\n[ \t]*\$\\square\$[ \t]*\n')
END_OF_PROOF = re.compile(r'^(\*\* Questions\b|\* )', re.MULTILINE)


def convert(text: str) -> str:
    text = SQUARE_LINE.sub('\n', text)

    out, pos = [], 0
    for m in PROOF_START.finditer(text):
        out.append(text[pos:m.start()])
        body_start = m.end()
        e = END_OF_PROOF.search(text, body_start)
        body_end = e.start() if e else len(text)
        body = text[body_start:body_end].rstrip()
        out.append(f"#+begin_proof\n{body}\n#+end_proof\n\n")
        pos = body_end
    out.append(text[pos:])
    return ''.join(out)


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: migrate_proofs.py FILE [FILE ...]", file=sys.stderr)
        sys.exit(1)

    for f in sys.argv[1:]:
        path = Path(f)
        orig = path.read_text()
        new = convert(orig)
        if orig != new:
            path.write_text(new)
            print(f"converted: {f}")
        else:
            print(f"unchanged: {f}")
