#!/usr/bin/env python3
"""Executable form of STRUCTURE.org.

STRUCTURE.org is the human-readable spec; this file is the machine-readable one.
When they disagree, one of them is wrong.

Exit codes:
    0  no findings outside the baseline
    1  new findings
    2  schema bug (self-check failed)
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

IGNORE_DIRS = {".git", "__pycache__", "node_modules", ".venv", ".ipynb_checkpoints"}
PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")   # matches {n}, not \d{2}


# --------------------------------------------------------------------------- #
# schema vocabulary
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class ChildRule:
    pattern: str
    kind: str
    required: bool = False
    rule_id: str = ""


@dataclass(frozen=True)
class FileRule:
    pattern: str
    required: bool = False
    rule_id: str = ""


@dataclass(frozen=True)
class Node:
    children: tuple[ChildRule, ...] = ()
    files: tuple[FileRule, ...] = ()
    unchecked: bool = False


@dataclass(frozen=True)
class Finding:
    rule_id: str
    path: str
    message: str

    def key(self) -> str:
        return f"{self.rule_id}\t{self.path}"


def bind(pattern: str, caps: dict) -> str:
    """Substitute {name} placeholders from inherited captures.

    Own placeholder syntax rather than str.format, because
    r"\\d{2}".format(n="01") raises IndexError.
    """
    def sub(m):
        key = m.group(1)
        if key not in caps:
            raise KeyError(f"unbound placeholder {{{key}}} in {pattern!r}")
        return re.escape(caps[key])
    return PLACEHOLDER.sub(sub, pattern)


# --------------------------------------------------------------------------- #
# the spec
# --------------------------------------------------------------------------- #

SCHEMA = {

    "ROOT": Node(
        children=(
            ChildRule(r"^00_global$",     kind="GLOBAL",     required=True, rule_id="R001"),
            ChildRule(r"^01_coursework$", kind="COURSEWORK", required=True, rule_id="R002"),
        ),
        files=(
            FileRule(r"^README\.md$",     required=True, rule_id="R010"),
            FileRule(r"^LICENSE$",        required=True, rule_id="R011"),
            FileRule(r"^STRUCTURE\.org$", required=True, rule_id="R012"),
            FileRule(r"^\.gitignore$",                   rule_id="R013"),
        ),
    ),

    # ----------------------------- 00_global ------------------------------- #

    "GLOBAL": Node(
        children=(
            ChildRule(r"^_archive$",   kind="ARCHIVE",   required=True, rule_id="G001"),
            ChildRule(r"^_llm_rules$", kind="LLM_RULES", required=True, rule_id="G002"),
            ChildRule(r"^books$",      kind="BOOKS",     required=True, rule_id="G003"),
            ChildRule(r"^scripts$",    kind="SCRIPTS",   required=True, rule_id="G004"),
        ),
        files=(),
    ),

    "ARCHIVE": Node(
        children=(),
        files=(FileRule(r"^[a-z0-9_]+\.(org|pdf)$", rule_id="A001"),),
    ),

    # _llm_rules mirrors the course facet taxonomy; every facet gets the same
    # two-level shape: 00_general/ plus optional 01_course_specific/<course>/.
    "LLM_RULES": Node(
        children=(ChildRule(r"^0[1-3]_[a-z_]+$", kind="LLM_FACET", required=True, rule_id="L001"),),
        files=(),
    ),
    "LLM_FACET": Node(
        children=(ChildRule(r"^course_specific$", kind="LLM_COURSE_SPLIT", rule_id="L010"),),
        files=(FileRule(r"^[a-z0-9_]+\.org$", rule_id="L011"),),
    ),
    "LLM_COURSE_SPLIT": Node(
        children=(ChildRule(r"^\d{2}_[a-z0-9_]+$", kind="LLM_COURSE_DIR", required=True, rule_id="L020"),),
        files=(),
    ),
    "LLM_COURSE_DIR": Node(
        children=(),
        files=(FileRule(r"^[a-z0-9_]+\.org$", rule_id="L030"),),
    ),

    # books/NN_subject/<slug>_book.pdf
    # Subject dirs may be empty, hence absent in a fresh clone: nothing required.
    "BOOKS": Node(
        children=(ChildRule(r"^\d{2}_[a-z0-9_]+$", kind="BOOKS_SUBJECT", rule_id="B001"),),
        files=(),
    ),
    "BOOKS_SUBJECT": Node(
        children=(),
        files=(FileRule(r"^[a-z0-9_]+_book\.pdf$", rule_id="B010"),),
    ),

    "SCRIPTS": Node(
        children=(),
        files=(FileRule(r"^[a-z0-9_]+\.py$", rule_id="T001"),),
    ),

    # ---------------------------- 01_coursework ---------------------------- #

    "COURSEWORK": Node(
        children=(ChildRule(r"^\d{2}_semester$", kind="SEMESTER",
                            required=True, rule_id="C001"),),
        files=(),
    ),
    "SEMESTER": Node(
        children=(ChildRule(r"^\d{2}_[a-z0-9_]+$", kind="COURSE",
                            required=True, rule_id="S001"),),
        files=(),
    ),
    "COURSE": Node(
        children=(
            ChildRule(r"^01_material$", kind="MATERIAL", required=True, rule_id="C010"),
            ChildRule(r"^02_problems$", kind="PROBLEMS", required=True, rule_id="C011"),
            ChildRule(r"^03_exams$",    kind="EXAMS",                  rule_id="C012"),
        ),
        files=(),
    ),

    # 01_material is flat: children=() IS the deprecation check for
    # lecture_org/ + lecture_pdf/ + lecture_notes/ + theorems/.
    "MATERIAL": Node(
        children=(),
        files=(
            FileRule(r"^ch_\d{2}_[a-z0-9_]+\.org$",              rule_id="M001"),
            FileRule(r"^(?!ch_)[a-z0-9_]+\.org$",                rule_id="M002"),
            FileRule(r"^_[a-z0-9_]+_source(_[a-z0-9_]+)?\.pdf$", rule_id="M003"),
        ),
    ),

    "PROBLEMS": Node(
        children=(ChildRule(r"^ps_(?P<n>\d{2})$", kind="PS",
                            required=True, rule_id="Q001"),),
        files=(),
    ),
    "PS": Node(
        children=(ChildRule(r"^assets$", kind="PS_ASSETS", rule_id="P001"),),
        files=(
            FileRule(r"^ps_{n}\.(org|pdf)$",        required=True, rule_id="P002"),
            FileRule(r"^ps_{n}_source\.pdf$",                rule_id="P003"),
            FileRule(r"^ps_{n}\.ipynb$",                     rule_id="P004"),
        ),
    ),
    # p_<NN>(_<part>)*(_<slug>)?.<ext>   part = zero-padded index or a letter
    "PS_ASSETS": Node(
        children=(),
        files=(FileRule(r"^p_\d{2}(_(\d{2}|[a-z]))*(_[a-z][a-z0-9_]*)?\.(png|gif|svg)$",
                        rule_id="P010"),),
    ),

    # 03_exams is [PROVISIONAL] in STRUCTURE.org. Hardening a provisional rule
    # into executable form freezes it prematurely. Enter, check nothing.
    "EXAMS": Node(unchecked=True),
}


# --------------------------------------------------------------------------- #
# self-check: validate the validator
# --------------------------------------------------------------------------- #

def _die(msg: str):
    print(f"schema bug: {msg}", file=sys.stderr)
    raise SystemExit(2)


def check_schema() -> None:
    ids = []
    for kind, node in SCHEMA.items():
        for r in node.children:
            if r.kind not in SCHEMA:
                _die(f"{kind} -> undefined kind {r.kind!r}")
        for r in node.children + node.files:
            probe = PLACEHOLDER.sub("00", r.pattern)      # dummy-bind everything
            try:
                re.compile(probe)
            except re.error as exc:
                _die(f"{kind}/{r.rule_id}: bad pattern {r.pattern!r}: {exc}")
            ids.append(r.rule_id)

    bad = sorted({i for i in ids if not i or ids.count(i) > 1})
    if bad:
        _die(f"duplicate or empty rule_ids: {bad}")

    # Reachability, plus: every {placeholder} a node uses must be bound by some
    # capture group on every path from ROOT to that node. Without this, a typo
    # like {m} for {n} survives startup and raises KeyError mid-walk.
    avail = {"ROOT": frozenset()}
    frontier = ["ROOT"]
    while frontier:
        kind = frontier.pop()
        node, caps = SCHEMA[kind], avail[kind]
        for r in node.children + node.files:
            need = set(PLACEHOLDER.findall(r.pattern))
            if not need <= set(caps):
                _die(f"{kind}/{r.rule_id}: unbound placeholder(s) "
                     f"{sorted(need - set(caps))} in {r.pattern!r}")
        for r in node.children:
            child_caps = caps | frozenset(re.compile(r.pattern).groupindex)
            if r.kind not in avail:
                avail[r.kind] = child_caps
                frontier.append(r.kind)
            elif not child_caps >= avail[r.kind]:
                # reached by a second path binding fewer names: narrow and redo
                avail[r.kind] = avail[r.kind] & child_caps
                frontier.append(r.kind)

    orphans = sorted(set(SCHEMA) - set(avail))
    if orphans:
        _die(f"unreachable kinds: {orphans}")


# --------------------------------------------------------------------------- #
# the walk
# --------------------------------------------------------------------------- #

def walk(dirpath: Path, kind: str, caps: dict, root: Path, out: list) -> None:
    node = SCHEMA[kind]
    if node.unchecked:
        return

    def rel(p) -> str:
        return str(Path(p).relative_to(root))

    entries = sorted(os.scandir(dirpath), key=lambda e: e.name)
    dirs = [e for e in entries if e.is_dir() and e.name not in IGNORE_DIRS]
    files = [e for e in entries if e.is_file()]

    matched = set()

    # coverage: every directory present must match some rule
    for e in dirs:
        for r in node.children:
            m = re.match(bind(r.pattern, caps), e.name)
            if m:
                matched.add(r.rule_id)
                walk(Path(e.path), r.kind, {**caps, **m.groupdict()}, root, out)
                break
        else:
            out.append(Finding(f"{kind}.DIR", rel(e.path), "unexpected directory"))

    # coverage: every file present must match some rule
    for e in files:
        for r in node.files:
            if re.match(bind(r.pattern, caps), e.name):
                matched.add(r.rule_id)
                break
        else:
            out.append(Finding(f"{kind}.FILE", rel(e.path), "unexpected file"))

    # completeness: every required rule must have matched at least once
    for r in node.children + node.files:
        if r.required and r.rule_id not in matched:
            out.append(Finding(r.rule_id, rel(dirpath),
                               f"missing required entry matching {r.pattern}"))


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def find_root() -> Path:
    root = Path(__file__).resolve().parents[2]      # scripts/ -> 00_global/ -> repo
    if not (root / "STRUCTURE.org").is_file():
        sys.exit(f"derived root {root} has no STRUCTURE.org - script moved?")
    return root


def load_baseline(path: Path) -> set:
    if not path.is_file():
        return set()
    return {ln.rstrip("\n") for ln in path.read_text().splitlines()
            if ln.strip() and not ln.startswith("#")}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="validate repo structure")
    ap.add_argument("--root", type=Path, default=None)
    ap.add_argument("--baseline", type=Path, default=None,
                    help="findings listed here are accepted "
                         "(default: 00_global/scripts/structure_baseline.txt)")
    ap.add_argument("--write-baseline", action="store_true",
                    help="overwrite the baseline with current findings")
    ap.add_argument("--strict", action="store_true", help="ignore the baseline")
    ap.add_argument("--summary", action="store_true", help="counts per rule only")
    args = ap.parse_args(argv)

    check_schema()

    root = args.root.resolve() if args.root else find_root()
    baseline_path = args.baseline or (root / "00_global/scripts/structure_baseline.txt")

    findings = []
    walk(root, "ROOT", {}, root, findings)
    findings.sort(key=lambda f: (f.rule_id, f.path))

    if args.write_baseline:
        baseline_path.write_text(
            "# accepted structure violations - may only shrink\n"
            + "".join(f.key() + "\n" for f in findings))
        print(f"wrote {len(findings)} findings to {baseline_path}")
        return 0

    accepted = set() if args.strict else load_baseline(baseline_path)
    new = [f for f in findings if f.key() not in accepted]

    if args.summary:
        counts = {}
        for f in new:
            counts[f.rule_id] = counts.get(f.rule_id, 0) + 1
        for rid, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
            print(f"{n:5}  {rid}")
    else:
        for f in new:
            print(f"{f.rule_id:16} {f.path}: {f.message}")

    stale = len(accepted) - (len(findings) - len(new))
    if stale > 0:
        print(f"\n{stale} baselined finding(s) no longer occur - "
              f"rerun with --write-baseline to shrink the baseline")

    print(f"\n{len(new)} new finding(s), {len(findings) - len(new)} baselined")
    return 1 if new else 0


if __name__ == "__main__":
    raise SystemExit(main())
