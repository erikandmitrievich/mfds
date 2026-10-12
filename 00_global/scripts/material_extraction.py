#!/usr/bin/env python3
"""material_extraction.py — screenshots of course material -> a course's
staging file, via the Anthropic API.

Takes every image in --inbox, oldest first by creation time, and sends them as
one batch, each labelled "Screenshot k/N". The system prompt is built from two
Org files, each with its #+ header dropped: math_notation.org inside
<math_notation> tags, followed by the material extraction rule. The reply is
checked, its item headings are aligned, and it is appended to --out, the
course's staging file (01_material/_extracted_ignore.org), under a
"* Batch <time>" heading. Items are refiled into ch_/lec_ files by hand.

The write only ever appends: the staging file may hold several unsorted
batches, and nothing in it is overwritten. Screenshots are never deleted here;
`just inbox-clear` does that once the output has been checked.

Checks, in code rather than in the prompt:
  before the call  the inbox holds images; they span at most an hour (--force
                   lifts this); each one fits the API's image limits
  after the call   a truncated or unfenced reply is not written (it goes to
                   stdout instead); every item has a drawer whose CUSTOM_ID
                   matches its type and is new to the course, a LECTURE_REF
                   not already in the course, and exactly one empty
                   ** Questions. These only warn: the batch is still written,
                   because it is reviewed before anything leaves the staging
                   file.

Marks, in code rather than in the prompt: every item's drawer gets
":LLM: <model>", the --model the batch was sent to. An LLM line the reply
wrote itself is dropped; an item with no drawer gets one holding only LLM.

Existing CUSTOM_IDs and LECTURE_REFs are read from every .org file next to
--out, i.e. the course's 01_material/, staging file included.

Paths are resolved by the justfile; this script takes concrete paths.
Shared helpers live in extraction_common.py.
Env: ANTHROPIC_API_KEY_MFDS.
"""

from __future__ import annotations

import argparse
import base64
import re
import struct
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from extraction_common import (DEFAULT_MODEL, build_system_prompt, call_api,
                               print_usage, reply_text, truncated, unfence)

DEFAULT_MAX_TOKENS = 32000

IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
MAX_SPAN_S = 60 * 60                  # one sitting; more means a stray file
MAX_IMAGE_B64 = 10_000_000            # API: 10 MB per image, base64-encoded
MANY_IMAGES = 20                      # API: above this many images per request,
MANY_IMAGES_MAX_PX = 2000             # ... no side may exceed this

KINDS = {"Definition": "def", "Proposition": "prop", "Lemma": "lem",
         "Corollary": "cor", "Theorem": "thm"}
TITLE_COL = len("Proposition:") + 1   # "* Proposition: X" — titles align here
REPORT_HEADING = "* Extraction report"

ITEM_HEAD_RE = re.compile(
    r"^\* (" + "|".join(KINDS) + r"):[ \t]+(\S.*?)\s*$")
TOP_HEAD_RE = re.compile(r"^\* ")
SUB_HEAD_RE = re.compile(r"^\*\*+ ")
PROP_RE = re.compile(r"^:([A-Za-z_]+):[ \t]*(.*?)\s*$")
LLM_PROP_RE = re.compile(r"^\s*:LLM:", re.I)
CUSTOM_ID_RE = re.compile(r"^(def|prop|lem|cor|thm):[a-z0-9]+(?:-[a-z0-9]+)*$")
MARKERS = {"uncertain": re.compile(r"\[\?:"),
           "illegible": re.compile(r"\[ILLEGIBLE:"),
           "cut off":   re.compile(r"\[CUT OFF:")}

HEADER = """\
#+title: Extracted
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


# --------------------------------------------------------------------------- #
# the inbox
# --------------------------------------------------------------------------- #

@dataclass
class Shot:
    path: Path
    created: float
    size: int
    dims: tuple[int, int] | None      # None when not a readable PNG

    @property
    def media_type(self) -> str:
        return IMAGE_TYPES[self.path.suffix.lower()]

    @property
    def b64_size(self) -> int:
        return 4 * ((self.size + 2) // 3)


def created_at(path: Path) -> float:
    """Creation time on macOS; modification time where there is none."""
    st = path.stat()
    return getattr(st, "st_birthtime", st.st_mtime)


def png_dims(path: Path) -> tuple[int, int] | None:
    with path.open("rb") as f:
        head = f.read(24)
    if head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", head[16:24])


def collect(inbox: Path) -> list[Shot]:
    """Images in the inbox, oldest first. Filenames play no part in the order:
    macOS names use a 12-hour clock that does not sort as text."""
    shots = []
    for p in inbox.iterdir():
        if p.name.startswith(".") or not p.is_file():
            continue
        if p.suffix.lower() not in IMAGE_TYPES:
            continue
        dims = png_dims(p) if p.suffix.lower() == ".png" else None
        shots.append(Shot(p, created_at(p), p.stat().st_size, dims))
    return sorted(shots, key=lambda s: (s.created, s.path.name))


def preflight(shots: list[Shot], force: bool) -> tuple[list[str], list[str]]:
    """(refusals, warnings) for a batch, before anything is sent."""
    refuse, warn = [], []
    if not shots:
        return ["the inbox holds no images (.png, .jpg)"], warn

    span = shots[-1].created - shots[0].created
    if span > MAX_SPAN_S:
        msg = (f"the batch spans {span / 60:.0f} min (oldest "
               f"{shots[0].path.name}); a stray screenshot?")
        (warn if force else refuse).append(
            msg + ("" if force else " Pass --force to send it anyway."))

    for s in shots:
        if s.b64_size > MAX_IMAGE_B64:
            refuse.append(f"{s.path.name} is {s.size // 1024} KiB; the API "
                          f"limit is 10 MB per image, base64-encoded")

    if len(shots) > MANY_IMAGES:
        big = [s for s in shots
               if s.dims and max(s.dims) > MANY_IMAGES_MAX_PX]
        unknown = [s for s in shots if s.dims is None]
        if big:
            refuse.append(
                f"{len(shots)} images in one batch: above {MANY_IMAGES}, the "
                f"API rejects any image wider or taller than "
                f"{MANY_IMAGES_MAX_PX} px, and {len(big)} "
                f"{'exceeds' if len(big) == 1 else 'exceed'} that (e.g. "
                f"{big[0].path.name}, {big[0].dims[0]}x{big[0].dims[1]}). "
                f"Split the batch or crop smaller.")
        if unknown:
            warn.append(f"{len(unknown)} image(s) are not PNG; their size "
                        f"against the {MANY_IMAGES_MAX_PX} px limit is unchecked")
    return refuse, warn


def batch_content(shots: list[Shot], used_ids: set[str]) -> list[dict]:
    """The user turn: each image after its label, then the instruction."""
    n = len(shots)
    content: list[dict] = []
    for k, s in enumerate(shots, 1):
        content.append({"type": "text", "text": f"Screenshot {k}/{n}:"})
        content.append({
            "type": "image",
            "source": {"type": "base64",
                       "media_type": s.media_type,
                       "data": base64.standard_b64encode(
                           s.path.read_bytes()).decode()},
        })
    ids = ("\n".join(sorted(used_ids)) if used_ids
           else "(none yet)")
    content.append({
        "type": "text",
        "text": (f"Process the {n} screenshots above according to the rules.\n\n"
                 f"CUSTOM_IDs already used in this course's notes "
                 f"(never reuse one):\n{ids}"),
    })
    return content


# --------------------------------------------------------------------------- #
# the course's notes
# --------------------------------------------------------------------------- #

def known_items(notes_dir: Path) -> tuple[set[str], set[tuple[str, str]]]:
    """CUSTOM_IDs, and (type, LECTURE_REF) pairs, in every .org file of the
    directory. The type is the heading's first word, so pre-convention
    headings (* Definition 10.1.1: ...) count too."""
    ids: set[str] = set()
    refs: set[tuple[str, str]] = set()
    if not notes_dir.is_dir():
        return ids, refs
    for f in sorted(notes_dir.glob("*.org")):
        kind = ""
        for ln in f.read_text(encoding="utf-8").splitlines():
            if TOP_HEAD_RE.match(ln):
                kind = ln[2:].split(" ", 1)[0].rstrip(":")
                continue
            m = PROP_RE.match(ln)
            if not m:
                continue
            key, val = m.group(1).upper(), m.group(2)
            if key == "CUSTOM_ID" and val:
                ids.add(val)
            elif key == "LECTURE_REF" and comparable_ref(val):
                refs.add((kind, val))
    return ids, refs


def comparable_ref(ref: str) -> bool:
    return bool(ref) and ref != "none" and "[?" not in ref


# --------------------------------------------------------------------------- #
# the reply
# --------------------------------------------------------------------------- #

@dataclass
class Item:
    kind: str
    title: str
    drawer: bool = False
    props: dict[str, str] = field(default_factory=dict)
    questions: int = 0
    questions_body: bool = False

    def label(self) -> str:
        return f"{self.kind} {self.props.get('LECTURE_REF', '?')} ({self.title})"


def align(org: str) -> tuple[str, list[Item], list[str]]:
    """Pad item headings so titles align, and parse items for checking.

    Returns (aligned org, items, warnings about structure the parse saw)."""
    out, items, warn = [], [], []
    item: Item | None = None
    in_drawer = in_questions = False
    prev_was_heading = False

    for ln in org.splitlines():
        m = ITEM_HEAD_RE.match(ln)
        if m:
            kind, title = m.group(1), m.group(2)
            item = Item(kind, title)
            items.append(item)
            in_drawer = in_questions = False
            out.append(f"* {kind + ':':<{TITLE_COL}}{title}")
            prev_was_heading = True
            continue

        if TOP_HEAD_RE.match(ln):
            if ln.rstrip() != REPORT_HEADING:
                warn.append(f"unexpected top-level heading: {ln.strip()}")
            item = None
            in_drawer = in_questions = False
        elif item is not None:
            if prev_was_heading and ln.strip() == ":PROPERTIES:":
                item.drawer = in_drawer = True
            elif in_drawer:
                if ln.strip() == ":END:":
                    in_drawer = False
                else:
                    p = PROP_RE.match(ln)
                    if p:
                        item.props[p.group(1).upper()] = p.group(2)
            elif SUB_HEAD_RE.match(ln):
                in_questions = ln.rstrip() == "** Questions"
                if in_questions:
                    item.questions += 1
            elif in_questions and ln.strip():
                item.questions_body = True

        prev_was_heading = False
        out.append(ln)

    return "\n".join(out).rstrip("\n") + "\n", items, warn


def stamp(org: str, model: str) -> tuple[str, int]:
    """Put ":LLM: <model>" last in the drawer of every item.

    The mark is written here, never by the rule, so an LLM line in the reply
    is dropped. An item without a drawer (check() warns about it) gets one
    holding only LLM, so the mark survives a hand-made fix of the drawer.
    Returns (org, number of items stamped)."""
    mark = f":LLM: {model}"
    lines = org.splitlines()
    out: list[str] = []
    n = i = 0
    while i < len(lines):
        ln = lines[i]
        out.append(ln)
        i += 1
        if not ITEM_HEAD_RE.match(ln):
            continue
        n += 1
        if i < len(lines) and lines[i].strip() == ":PROPERTIES:":
            out.append(lines[i])
            i += 1
            while i < len(lines) and lines[i].strip() != ":END:":
                if not LLM_PROP_RE.match(lines[i]):
                    out.append(lines[i])
                i += 1
            out.append(mark)                    # :END: follows on the next pass
            if i == len(lines):
                out.append(":END:")             # unterminated in the reply
        else:
            out.extend([":PROPERTIES:", mark, ":END:"])
    return "\n".join(out).rstrip("\n") + "\n", n


def check(items: list[Item], used_ids: set[str],
          used_refs: set[tuple[str, str]]) -> list[str]:
    warn, seen = [], set()
    for it in items:
        where = it.label()
        if not it.drawer:
            warn.append(f"{where}: no property drawer directly under the heading")
        cid = it.props.get("CUSTOM_ID", "")
        if not cid:
            warn.append(f"{where}: no CUSTOM_ID")
        elif not CUSTOM_ID_RE.match(cid):
            warn.append(f"{where}: malformed CUSTOM_ID {cid}")
        elif cid.split(":", 1)[0] != KINDS[it.kind]:
            warn.append(f"{where}: CUSTOM_ID {cid} has the wrong prefix "
                        f"for a {it.kind} ({KINDS[it.kind]}:)")
        ref = it.props.get("LECTURE_REF", "")
        if not ref:
            warn.append(f"{where}: no LECTURE_REF")

        id_known = bool(cid) and cid not in seen and cid in used_ids
        ref_known = comparable_ref(ref) and (it.kind, ref) in used_refs
        if cid and cid in seen:
            warn.append(f"{where}: CUSTOM_ID {cid} appears twice in this batch")
        if id_known and ref_known:
            warn.append(f"{where}: already in the course (same CUSTOM_ID and "
                        f"number); extracted before?")
        elif id_known:
            warn.append(f"{where}: CUSTOM_ID {cid} is already used in the course")
        elif ref_known:
            warn.append(f"{where}: {it.kind} {ref} is already in the course "
                        f"(extracted before?)")
        seen.add(cid)

        if it.questions != 1:
            warn.append(f"{where}: {it.questions} ** Questions headings, "
                        f"expected 1")
        if it.questions_body:
            warn.append(f"{where}: ** Questions is not empty")
    return warn


def marker_counts(org: str) -> dict[str, int]:
    return {name: len(rx.findall(org)) for name, rx in MARKERS.items()}


# --------------------------------------------------------------------------- #
# the staging file
# --------------------------------------------------------------------------- #

def batch_block(org: str, n: int, now: datetime) -> str:
    return f"* Batch {now:%Y-%m-%d %H:%M} ({n} screenshots)\n\n{org}"


def append(out: Path, block: str, now: datetime) -> None:
    """Append block to out, creating out with the standard header if absent.
    Exactly one blank line separates the block from what is already there."""
    if not out.exists():
        out.write_text(HEADER.format(date=f"{now:%Y-%m-%d}",
                                     time=f"{now:%H:%M}"), encoding="utf-8")
    text = out.read_text(encoding="utf-8").rstrip("\n")
    out.write_text(text + "\n\n" + block.rstrip("\n") + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def report(lines: list[str], title: str, stream=sys.stderr) -> None:
    if lines:
        print(f"{title}:", file=stream)
        for ln in lines:
            print(f"  - {ln}", file=stream)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--inbox", required=True, type=Path,
                    help="folder of screenshots; every image in it is sent")
    ap.add_argument("--rule", required=True, type=Path,
                    help="material extraction rule")
    ap.add_argument("--notation", required=True, type=Path,
                    help="math_notation.org (math rules the extraction rule "
                         "delegates to)")
    ap.add_argument("--out", required=True, type=Path,
                    help="the course's staging file; appended to, created "
                         "with a header if absent")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    ap.add_argument("--force", action="store_true",
                    help="send a batch that spans more than an hour")
    ap.add_argument("--stdout", action="store_true",
                    help="print the batch instead of appending it to --out")
    ap.add_argument("--dry-run", action="store_true",
                    help="list the batch and report; make no API call")
    args = ap.parse_args()

    for label, p in (("rule file", args.rule),
                     ("notation file", args.notation)):
        if not p.is_file():
            print(f"no {label}: {p}", file=sys.stderr)
            return 1
    if not args.inbox.is_dir():
        print(f"no inbox: {args.inbox}", file=sys.stderr)
        return 1
    if not args.out.parent.is_dir():
        print(f"no notes directory: {args.out.parent}", file=sys.stderr)
        return 1

    shots = collect(args.inbox)
    refuse, warn = preflight(shots, args.force)
    used_ids, used_refs = known_items(args.out.parent)

    if args.dry_run:
        for k, s in enumerate(shots, 1):
            dims = f"{s.dims[0]}x{s.dims[1]}" if s.dims else "?"
            print(f"{k:>3}  {datetime.fromtimestamp(s.created):%H:%M:%S}  "
                  f"{dims:>9}  {s.size // 1024:>6} KiB  {s.path.name}")
        if shots:
            span = (shots[-1].created - shots[0].created) / 60
            print(f"batch     {len(shots)} screenshots over {span:.0f} min")
        print(f"inbox     {args.inbox}")
        print(f"rule      {args.rule}")
        print(f"notation  {args.notation}")
        print(f"out       {args.out}{'  [EXISTS]' if args.out.exists() else ''}")
        print(f"course    {len(used_ids)} CUSTOM_IDs, {len(used_refs)} "
              f"LECTURE_REFs in {args.out.parent}")
        print(f"model     {args.model}   max_tokens {args.max_tokens}")
        report(warn, "warnings", sys.stdout)
        if refuse:
            report(refuse, "would REFUSE", sys.stdout)
        else:
            print("would " + ("print the batch" if args.stdout
                              else f"append to {args.out.name}"))
        return 0

    report(warn, "warnings")
    if refuse:
        report(refuse, "refusing")
        return 1

    system = build_system_prompt(args.rule, args.notation)
    print(f"extracting {len(shots)} screenshots -> {args.out.name} "
          f"[{args.model}] ...", file=sys.stderr)
    msg = call_api(batch_content(shots, used_ids), system,
                   args.model, args.max_tokens)

    org, fenced = unfence(reply_text(msg))
    print_usage(msg)

    if truncated(msg) or not fenced:
        why = ("hit max_tokens — output truncated; re-run with a larger "
               "--max-tokens" if truncated(msg)
               else "no ```org fence in the reply")
        print(f"WARNING: {why}. Not writing; dumping to stdout.",
              file=sys.stderr)
        sys.stdout.write(org)
        return 1

    org, items, struct_warn = align(org)
    org, _ = stamp(org, args.model)
    findings = struct_warn + check(items, used_ids, used_refs)
    block = batch_block(org, len(shots), datetime.now())

    if args.stdout:
        sys.stdout.write(block)
    else:
        append(args.out, block, datetime.now())
        print(f"appended {len(items)} item(s) to {args.out}", file=sys.stderr)

    counts = marker_counts(org)
    print("markers: " + ", ".join(f"{v} {k}" for k, v in counts.items()),
          file=sys.stderr)
    report(findings, "check these")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
