#!/usr/bin/env python3
"""Executable form of STRUCTURE.org.

STRUCTURE.org is the human-readable spec; this file is the machine-readable one.
When they disagree, this file wins and STRUCTURE.org gets fixed.

Scope is the directory tree: which directories may exist where, what files may
be named, what must be present. File contents are never read.

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
    # Groups of rule_ids that must not both match inside one directory.
    # Used where the spec says "either this shape or that one, never mixed".
    exclusive: tuple[tuple[str, ...], ...] = ()


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
# Scope: names and shapes only. This validator reads the directory tree, never
# file contents. Anything that requires opening a file -- header conventions,
# CUSTOM_ID format, math delimiters -- belongs to a separate content validator,
# not here. Keeping the boundary sharp is why there is no --content flag: an
# empty extension point is the same drift as a commented-out rule.
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# exam stage vocabulary
# --------------------------------------------------------------------------- #

_STAGES = (
    ("00_resources",   "EXAM_RESOURCES",   "E010"),
    ("01_extracted",   "EXAM_EXTRACTED",   "E011"),
    ("02_plan",        "EXAM_PLAN",        "E012"),
    ("03_preparation", "EXAM_PREPARATION", "E013"),
    ("04_revision",    "EXAM_REVISION",    "E014"),
)

_EXAM_STAGES = tuple(
    ChildRule(rf"^{name}$", kind=kind, rule_id=rid) for name, kind, rid in _STAGES
)
_STAGE_IDS = tuple(rid for _, _, rid in _STAGES)

# A stack directory is NN_<slug> that is not itself a stage name. Without the
# lookahead a typo (01_extracte) is silently accepted as a stack, and nothing
# underneath it is ever checked.
_NOT_A_STAGE = "|".join(name for name, _, _ in _STAGES)
_EXAM_STACK = ChildRule(
    rf"^\d{{2}}_(?!(?:{_NOT_A_STAGE})$)[a-z0-9_]+$", kind="EXAM_STACK", rule_id="E001"
)


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
            FileRule(r"^justfile$",       required=True, rule_id="R014"),
        ),
    ),

    # ----------------------------- 00_global ------------------------------- #

    "GLOBAL": Node(
        children=(
            ChildRule(r"^archive$", kind="ARCHIVE",                rule_id="G001"),
            ChildRule(r"^prompts$", kind="PROMPTS", required=True, rule_id="G002"),
            ChildRule(r"^books$",   kind="BOOKS",                  rule_id="G003"),
            ChildRule(r"^scripts$", kind="SCRIPTS", required=True, rule_id="G004"),
        ),
        files=(),
    ),

    "ARCHIVE": Node(
        children=(),
        files=(FileRule(r"^[a-z0-9_]+\.(org|pdf)$", rule_id="A001"),),
    ),

    "PROMPTS": Node(
        children=(ChildRule(r"^0[1-3]_[a-z_]+$", kind="PROMPT_FACET", required=True, rule_id="L001"),),
        files=(),
    ),
    "PROMPT_FACET": Node(
        children=(ChildRule(r"^course_specific$", kind="PROMPT_COURSE_SPLIT", rule_id="L010"),),
        files=(FileRule(r"^[a-z0-9_]+\.org$", rule_id="L011"),),
    ),
    "PROMPT_COURSE_SPLIT": Node(
        children=(ChildRule(r"^\d{2}_[a-z0-9_]+$", kind="PROMPT_COURSE_DIR", required=True, rule_id="L020"),),
        files=(),
    ),
    "PROMPT_COURSE_DIR": Node(
        children=(),
        files=(FileRule(r"^[a-z0-9_]+\.org$", rule_id="L030"),),
    ),

    "BOOKS": Node(
        children=(ChildRule(r"^\d{2}_[a-z0-9_]+$", kind="BOOKS_SUBJECT", rule_id="B001"),),
        files=(),
    ),
    "BOOKS_SUBJECT": Node(
        children=(),
        files=(FileRule(r"^[a-z0-9_]+_book\.pdf$", rule_id="B010"),),
    ),

    "SCRIPTS": Node(
        children=(ChildRule(r"^hooks$", kind="HOOKS", rule_id="T002"),),
        files=(
            FileRule(r"^[a-z0-9_]+\.py$",              rule_id="T001"),
            # written by --write-baseline; the default --baseline path lives here
            FileRule(r"^structure_baseline\.txt$",      rule_id="T003"),
        ),
    ),
    # git hooks are repo machinery and belong in the repo, not in .git/.
    # Enable with: git config core.hooksPath 00_global/scripts/hooks
    "HOOKS": Node(
        children=(),
        files=(FileRule(r"^(pre-commit|commit-msg|pre-push|prepare-commit-msg)$",
                        rule_id="T010"),),
    ),

    # ---------------------------- 01_coursework ---------------------------- #

    "COURSEWORK": Node(
        children=(ChildRule(r"^\d{2}_semester$", kind="SEMESTER", required=True, rule_id="C001"),),
        files=(),
    ),
    "SEMESTER": Node(
        children=(ChildRule(r"^\d{2}_[a-z0-9_]+$", kind="COURSE", required=True, rule_id="S001"),),
        files=(),
    ),
    "COURSE": Node(
        children=(
            ChildRule(r"^01_material$", kind="MATERIAL",                rule_id="C010"),
            ChildRule(r"^02_problems$", kind="PROBLEMS", required=True, rule_id="C011"),
            ChildRule(r"^03_exams$",    kind="EXAMS",                   rule_id="C012"),
        ),
        files=(),
    ),

    "MATERIAL": Node(
        children=(),
        files=(
            FileRule(r"^ch_\d{2}_[a-z0-9_]+\.org$",              rule_id="M001"),
            FileRule(r"^lec_\d{2}(-\d{2})?\.org$",               rule_id="M004"),
            FileRule(r"^(?!ch_|lec_)[a-z0-9_]+\.org$",           rule_id="M002"),
            FileRule(r"^_[a-z0-9_]+_source(_[a-z0-9_]+)?\.pdf$", rule_id="M003"),
        ),
    ),

    "PROBLEMS": Node(
        children=(ChildRule(r"^ps_(?P<n>\d{2})$", kind="PS", required=True, rule_id="Q001"),),
        files=(),
    ),
    "PS": Node(
        children=(ChildRule(r"^assets$", kind="PS_ASSETS", rule_id="P001"),),
        files=(
            FileRule(r"^ps_{n}\.(org|pdf)$",        required=True, rule_id="P002"),
            FileRule(r"^ps_{n}_source\.pdf$",                      rule_id="P003"),
            FileRule(r"^ps_{n}\.ipynb$",                           rule_id="P004"),
        ),
    ),
    "PS_ASSETS": Node(
        children=(),
        files=(FileRule(r"^p_\d{2}(_(\d{2}|[a-z]))*(_[a-z][a-z0-9_]*)?\.(png|gif|svg)$", rule_id="P010"),),
    ),

    # ------------------------------ 03_exams ------------------------------- #
    #
    # 03_exams is [PROVISIONAL] in STRUCTURE.org. Provisional applies to the
    # slug conventions, not to the invariants. Two tiers are enforced:
    #
    #   hard  stage vocabulary; stack-xor-stages; source/product separation
    #   soft  file slugs, left as [a-z0-9_]+ until a naming decision lands
    #
    # A stack (03_exams/0N_<exam>/) and bare stages (03_exams/00_resources/)
    # are mutually exclusive: the spec says a second exam splits one level up,
    # which means every exam in that course does.

    "EXAMS": Node(
        children=_EXAM_STAGES + (_EXAM_STACK,),
        files=(),
        exclusive=(_STAGE_IDS, ("E001",)),
    ),
    "EXAM_STACK": Node(children=_EXAM_STAGES, files=()),

    # 00_resources: irreplaceable INPUTS only. Every file either carries a
    # _source suffix, or is a curated note, or is a machine transcript. That is
    # the executable form of "rm -rf 01_extracted/ must be obviously safe".
    "EXAM_RESOURCES": Node(
        children=(
            ChildRule(r"^notes$",       kind="EXAM_NOTES",       rule_id="E020"),
            ChildRule(r"^transcripts$", kind="EXAM_TRANSCRIPTS", rule_id="E021"),
            ChildRule(r"^papers$",      kind="EXAM_PAPERS",      rule_id="E022"),
        ),
        files=(),
    ),
    "EXAM_NOTES": Node(
        children=(),
        files=(FileRule(r"^notes_[a-z0-9_]+\.(org|jpeg|png)$", rule_id="E030"),),
    ),
    "EXAM_TRANSCRIPTS": Node(
        children=(),
        files=(FileRule(r"^lec_\d{2}(-\d{2})?\.txt$", rule_id="E031"),),
    ),
    "EXAM_PAPERS": Node(
        children=(),
        files=(FileRule(r"^[a-z0-9_]+_source\.(pdf|jpeg|png)$", rule_id="E032"),),
    ),

    # 01_extracted: LLM build products. Disposable by construction -- everything
    # needed to rebuild them lives in 00_resources/ plus 00_global/prompts/.
    # Nothing here is required: which products a course needs is a property of
    # the course, not of the schema.
    "EXAM_EXTRACTED": Node(
        children=(),
        files=(
            FileRule(r"^material\.org$",           rule_id="E040"),
            FileRule(r"^theorems\.org$",           rule_id="E041"),
            FileRule(r"^problems\.org$",           rule_id="E042"),
            FileRule(r"^exam(_[a-z0-9_]+)?\.org$", rule_id="E043"),
        ),
    ),
    "EXAM_PLAN": Node(
        children=(),
        files=(FileRule(r"^plan\.org$", required=True, rule_id="E050"),),
    ),
    "EXAM_PREPARATION": Node(
        children=(ChildRule(r"^assets$", kind="EXAM_PREP_ASSETS", rule_id="E060"),),
        files=(FileRule(r"^day_\d{2}\.org$", required=True, rule_id="E061"),),
    ),
    "EXAM_PREP_ASSETS": Node(
        children=(),
        files=(FileRule(r"^ps_\d{2}(_\d{2})+\.(png|gif|svg)$", rule_id="E062"),),
    ),
    # 04_revision is optional as a whole and its file is named by the course,
    # not by convention: cheatsheet.org, summary.org, must_know_proofs.org are
    # all in use. One permissive rule, nothing required.
    "EXAM_REVISION": Node(
        children=(),
        files=(FileRule(r"^[a-z0-9_]+\.org$", rule_id="E070"),),
    ),
}


# --------------------------------------------------------------------------- #
# self-check: validate the validator
# --------------------------------------------------------------------------- #

def _die(msg: str):
    print(f"schema bug: {msg}", file=sys.stderr)
    raise SystemExit(2)


def check_schema() -> None:
    for kind, node in SCHEMA.items():
        for r in node.children:
            if r.kind not in SCHEMA:
                _die(f"{kind} -> undefined kind {r.kind!r}")

        ids = []
        for r in node.children + node.files:
            probe = PLACEHOLDER.sub("00", r.pattern)      # dummy-bind everything
            try:
                re.compile(probe)
            except re.error as exc:
                _die(f"{kind}/{r.rule_id}: bad pattern {r.pattern!r}: {exc}")
            ids.append(r.rule_id)

        # rule_ids are unique per node, not globally: the exam stage vocabulary
        # is deliberately shared between EXAMS and EXAM_STACK. Findings are
        # reported as KIND/RULE, so per-node uniqueness is enough to be
        # unambiguous.
        bad = sorted({i for i in ids if not i or ids.count(i) > 1})
        if bad:
            _die(f"{kind}: duplicate or empty rule_ids: {bad}")
        if {"DIR", "FILE", "MIX"} & set(ids):
            _die(f"{kind}: rule_id collides with a synthetic id (DIR/FILE/MIX)")

        for group in node.exclusive:
            unknown = sorted(set(group) - set(ids))
            if unknown:
                _die(f"{kind}: exclusive group names unknown rule_ids {unknown}")
        seen = [g for group in node.exclusive for g in group]
        if len(seen) != len(set(seen)):
            _die(f"{kind}: rule_id appears in more than one exclusive group")

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

    def rel(p) -> str:
        return str(Path(p).relative_to(root))

    def fid(rule_id: str) -> str:
        return f"{kind}/{rule_id}"

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
            out.append(Finding(fid("DIR"), rel(e.path), "unexpected directory"))
            # Report its contents too. Otherwise one unrecognised directory
            # hides an arbitrary subtree behind a single baselined finding.
            for sub, subdirs, subfiles in os.walk(e.path):
                subdirs[:] = [d for d in subdirs if d not in IGNORE_DIRS]
                for name in sorted(subfiles):
                    out.append(Finding(fid("DIR"), rel(Path(sub) / name),
                                       "inside unexpected directory"))

    # coverage: every file present must match some rule
    for e in files:
        for r in node.files:
            if re.match(bind(r.pattern, caps), e.name):
                matched.add(r.rule_id)
                break
        else:
            out.append(Finding(fid("FILE"), rel(e.path), "unexpected file"))

    # completeness: every required rule must have matched at least once
    for r in node.children + node.files:
        if r.required and r.rule_id not in matched:
            out.append(Finding(fid(r.rule_id), rel(dirpath),
                               f"missing required entry matching {r.pattern}"))

    # exclusivity: shapes that must not be mixed inside one directory
    live = [sorted(g for g in group if g in matched) for group in node.exclusive]
    live = [g for g in live if g]
    if len(live) > 1:
        out.append(Finding(fid("MIX"), rel(dirpath),
                           "mixed exclusive shapes: "
                           + " vs ".join(",".join(g) for g in live)))


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
            print(f"{f.rule_id:26} {f.path}: {f.message}")

    stale = len(accepted) - (len(findings) - len(new))
    if stale > 0:
        print(f"\n{stale} baselined finding(s) no longer occur - "
              f"rerun with --write-baseline to shrink the baseline")

    print(f"\n{len(new)} new finding(s), {len(findings) - len(new)} baselined")
    return 1 if new else 0


if __name__ == "__main__":
    raise SystemExit(main())
