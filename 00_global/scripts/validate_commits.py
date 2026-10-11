#!/usr/bin/env python3
"""Executable form of .gitmessage.

.gitmessage is the human-readable spec for commit messages, and git's commit
template; this file is the machine-readable one. When they disagree, this file
wins and .gitmessage gets fixed.

Scope is one commit: its message, and the paths it changes. Rule ids are
H-prefixed (history); C is taken by STRUCTURE.org's coursework rules.

Usage:
    validate_commits.py                    every commit after the cutoff
    validate_commits.py REVS...            commits in REVS after the cutoff
    validate_commits.py --message-file F   one message, against staged paths
    validate_commits.py --scopes           the scopes the tree admits
    validate_commits.py --prepare F [--source S]
                                           prefill type(scope) into F

The cutoff is the commit that added .gitmessage. It is read from history, not
stored, so there is no baseline: every later commit is checked, the cutoff and
everything before it never are.

Exit codes:
    0  no findings
    1  findings
    2  schema bug (self-check failed), or git refused a command
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]       # scripts/ -> 00_global/ -> repo
SPEC = ROOT / ".gitmessage"


# --------------------------------------------------------------------------- #
# the spec
# --------------------------------------------------------------------------- #

# Every id below must appear in .gitmessage and vice versa (self-check).
RULES = {
    "H001": "summary is <type>(<scope>)[!]: <summary>",
    "H002": "summary is at most 72 characters",
    "H003": "line 2 is blank",
    "H004": "type is in the vocabulary",
    "H005": "lowercase after the colon, no final period",
    "H006": "no opening filler, no wip",
    "H007": "no ' + ' joining two changes",
    "H008": "first word not past tense or gerund",
    "H010": "content scope is an existing course",
    "H011": "content verb is in the closed list",
    "H012": "content paths are inside <course>/0N_<type>/",
    "H013": "draft ends with what is open, in parentheses",
    "H020": "machinery scope is the component of a changed path",
    "H021": "no 01_coursework/ path unless the scope is coursework",
    "H030": "body present where required",
    "H031": "'!' if and only if a BREAKING CHANGE footer",
    "H032": "body lines at most 72 characters",
    "H040": "no fixup!/squash!/amend! in a checked range",
}

# Content: type = facet directory, scope = course directory without NN_.
FACETS = {"01_material": "material", "02_problems": "problems", "03_exams": "exams"}
CONTENT_TYPES = tuple(FACETS.values())
CONTENT_VERBS = ("scaffold", "draft", "solve", "add", "revise", "correct", "move", "remove")

# Machinery: everything outside 01_coursework/. Scope = component.
MACHINERY_TYPES = ("feat", "fix", "refactor", "docs", "chore", "revert")

BODY_TYPES = ("feat", "fix", "refactor", "revert")      # H030
BODY_VERBS = ("correct",)                               # H030
BREAKING_KEYS = ("BREAKING CHANGE", "BREAKING-CHANGE")  # H031

# H006: opening words that say nothing. "wip" is caught anywhere (PATTERNS).
FILLER_FIRST = ("minor", "misc", "some", "small", "various", "stuff", "things",
                "tweaks", "changes", "updates")
# H008: -ed/-ing first words that are imperatives anyway, and irregular pasts.
ED_ING_IMPERATIVES = ("embed", "shed", "shred", "seed", "need", "feed", "speed",
                      "bleed", "breed", "exceed", "proceed", "succeed", "bring",
                      "string", "ring", "sing", "ping", "swing", "sting", "spring")
IRREGULAR_PAST = ("wrote", "rewrote", "made", "did", "built", "rebuilt", "ran",
                  "took", "began", "got", "kept", "brought", "thought")

# Paths that belong to a named component rather than to their own stem.
# A spec and its validator are one component: they change together.
COMPONENTS = {
    ".gitmessage":                                "commits",
    "00_global/scripts/validate_commits.py":      "commits",
    "00_global/scripts/hooks/commit-msg":         "commits",
    "00_global/scripts/hooks/prepare-commit-msg": "commits",
    "00_global/scripts/hooks/pre-push":           "commits",
    "STRUCTURE.org":                              "structure",
    "00_global/scripts/validate_structure.py":    "structure",
    "00_global/scripts/structure_baseline.txt":   "structure",
    "00_global/scripts/hooks/pre-commit":         "structure",
    "README.md":                                  "readme",
    "justfile":                                   "justfile",
    ".gitignore":                                 "gitignore",
    "LICENSE":                                    "license",
}
COURSEWORK = "coursework"       # machinery scope for mechanical cross-course edits

PATTERNS = {
    # H001. Scope charset is the repo's snake_case; desc must start non-blank.
    "summary":    r"^(?P<type>[a-z]+)(?:\((?P<scope>[a-z0-9_]+)\))?(?P<bang>!)?: (?P<desc>\S.*)$",
    # Git's own messages: checked by nothing, except H040 in a range.
    "passthru":   r'^(?:Merge |Revert ")',
    "autosquash": r"^(?:fixup|squash|amend)! ",
    "trailer":    r"^(?P<key>BREAKING CHANGE|[A-Za-z][A-Za-z0-9-]*): \S",
    "scissors":   r"^# -+ >8 -+$",
    "course_dir": r"^\d{2}_(?P<slug>[a-z0-9_]+)$",
    "first_word": r"^[A-Za-z]+",
    "ed_ing":     r"^[a-z]+(?:ed|ing)$",
    "wip":        r"(?i)\bwip\b",
    "draft_open": r"\(\S.*\)$",
    "spec_ids":   r"\bH\d{3}\b",
    "rule_id":    r"^H\d{3}$",
    "scope":      r"^[a-z0-9_]+$",
}
RX: dict[str, re.Pattern] = {}          # filled by check_schema()

MAX_SUMMARY = 72
MAX_BODY = 72


# --------------------------------------------------------------------------- #
# self-check: validate the validator
# --------------------------------------------------------------------------- #

def _die(msg: str):
    print(f"schema bug: {msg}", file=sys.stderr)
    raise SystemExit(2)


def check_schema() -> None:
    for name, pattern in PATTERNS.items():
        try:
            RX[name] = re.compile(pattern)
        except re.error as exc:
            _die(f"pattern {name!r} does not compile: {exc}")

    for rid in RULES:
        if not RX["rule_id"].match(rid):
            _die(f"bad rule id {rid!r}")

    types = CONTENT_TYPES + MACHINERY_TYPES
    if len(set(types)) != len(types):
        _die("a type is both content and machinery, or listed twice")
    for t in types:
        if not re.fullmatch(r"[a-z]+", t):
            _die(f"type {t!r} would never match H001")
    if not set(BODY_TYPES) <= set(MACHINERY_TYPES):
        _die("BODY_TYPES names a type that does not exist")
    if not set(BODY_VERBS) <= set(CONTENT_VERBS):
        _die("BODY_VERBS names a verb that does not exist")
    if set(FILLER_FIRST) & set(CONTENT_VERBS):
        _die("a content verb is also filler")
    for comp in set(COMPONENTS.values()) | {COURSEWORK}:
        if not RX["scope"].match(comp):
            _die(f"component {comp!r} would never match H001")
    if COURSEWORK in COMPONENTS.values():
        _die(f"{COURSEWORK!r} is reserved for 01_coursework/ paths")

    # The agreement surface with .gitmessage: the same rule ids, no more, no less.
    if not SPEC.is_file():
        _die(f"{SPEC.name} not found at {ROOT} - the spec is gone, or the script moved")
    in_spec = set(RX["spec_ids"].findall(SPEC.read_text()))
    if in_spec != set(RULES):
        only_spec = ", ".join(sorted(in_spec - set(RULES))) or "-"
        only_code = ", ".join(sorted(set(RULES) - in_spec)) or "-"
        _die(f".gitmessage and validator disagree; only in .gitmessage: {only_spec}; "
             f"only in validator: {only_code}")


# --------------------------------------------------------------------------- #
# git
# --------------------------------------------------------------------------- #

def git(*args: str) -> str:
    r = subprocess.run(["git", "-C", str(ROOT), *args],
                       stdin=subprocess.DEVNULL, capture_output=True, text=True)
    if r.returncode:
        print(f"git {' '.join(args)}: {r.stderr.strip()}", file=sys.stderr)
        raise SystemExit(2)
    return r.stdout


def _z(out: str) -> list[str]:
    return [p for p in out.split("\0") if p]


def staged_paths() -> list[str]:
    # Honours GIT_INDEX_FILE, which git sets for `commit -a` and `commit <path>`.
    return _z(git("diff", "--cached", "--name-only", "--no-renames", "-z"))


def commit_paths(sha: str) -> list[str]:
    return _z(git("diff-tree", "--no-commit-id", "--name-only", "-r", "--no-renames",
                  "--root", "-z", sha))


def tracked_paths() -> list[str]:
    return _z(git("ls-files", "-z"))


def cutoff() -> str:
    adds = git("log", "--diff-filter=A", "--format=%H", "--", SPEC.name).split()
    if not adds:
        print(f"no commit adds {SPEC.name} - nothing to anchor the range", file=sys.stderr)
        raise SystemExit(2)
    return adds[-1]                                 # the oldest add


# --------------------------------------------------------------------------- #
# paths -> type and scope
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Where:
    component: str                  # the machinery scope this path belongs to
    course: str | None = None       # set for anything inside a course directory
    facet: str | None = None        # content type, set for paths inside a facet

    @property
    def content(self) -> str | None:
        """type(scope) for a content path, else None."""
        return f"{self.facet}({self.course})" if self.facet else None


def _slug(name: str) -> str:
    name = re.sub(r"^\d{2}_", "", name.lstrip("."))
    name = re.sub(r"\.[A-Za-z0-9]+$", "", name)
    return re.sub(r"[^a-z0-9_]", "_", name.lower()) or "root"


def where(path: str) -> Where:
    parts = path.split("/")
    if parts[0] == "01_coursework":
        course = facet = None
        if len(parts) >= 4:                                     # sem/course/<x>
            m = RX["course_dir"].match(parts[2])
            course = m["slug"] if m else None
        if course and len(parts) >= 5:                          # sem/course/facet/<x>
            facet = FACETS.get(parts[3])
        return Where(COURSEWORK, course, facet)

    if path in COMPONENTS:
        return Where(COMPONENTS[path])
    stem = Path(path).stem
    if parts[:2] == ["00_global", "scripts"] and len(parts) == 3 and path.endswith(".py"):
        return Where(stem)                                      # a script: its stem
    if parts[:2] == ["00_global", "prompts"] and path.endswith(".org"):
        return Where(stem)                                      # a prompt: its slug
    if parts[:2] == ["00_global", "archive"]:
        return Where("archive")
    if parts[:2] == ["00_global", "books"]:
        return Where("books")
    return Where(_slug(parts[0]))                               # unmapped: top segment


def courses_in(paths: list[str]) -> set[str]:
    return {w.course for w in map(where, paths) if w.course}


def components_in(paths: list[str]) -> set[str]:
    return {where(p).component for p in paths}


# --------------------------------------------------------------------------- #
# messages
# --------------------------------------------------------------------------- #

def clean(raw: str) -> list[str]:
    """What git keeps of a message under the default cleanup=strip."""
    lines = []
    for ln in raw.splitlines():
        if RX["scissors"].match(ln):
            break
        if ln.startswith("#"):
            continue
        lines.append(ln.rstrip())
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    out: list[str] = []
    for ln in lines:                                            # collapse blank runs
        if ln or (out and out[-1]):
            out.append(ln)
    return out


def split_body(lines: list[str]) -> tuple[list[str], list[str]]:
    """(body, trailers) of everything after the first paragraph.

    Git takes the whole first paragraph as the subject, so a wrapped summary's
    second line is subject, not body (H003 reports it).
    """
    gap = lines.index("") if "" in lines else len(lines)
    rest = lines[gap + 1:]
    paras: list[list[str]] = [[]]
    for ln in rest:
        if ln:
            paras[-1].append(ln)
        elif paras[-1]:
            paras.append([])
    paras = [p for p in paras if p]
    trailers: list[str] = []
    if paras and all(RX["trailer"].match(ln) or ln[:1].isspace() for ln in paras[-1]):
        trailers = paras.pop()
    return [ln for p in paras for ln in p], trailers


@dataclass(frozen=True)
class Finding:
    rule_id: str
    message: str


def check(lines: list[str], paths: list[str] | None, tree: list[str],
          in_range: bool = False) -> list[Finding]:
    """Findings for one cleaned message.

    paths  the paths the commit changes; None when unknowable, which turns the
           path rules (H012, H020's path half, H021) off rather than guessing
    tree   tracked paths, the source of the courses and components that exist
    """
    out: list[Finding] = []

    def find(rid: str, msg: str) -> None:
        assert rid in RULES, rid
        out.append(Finding(rid, msg))

    if not lines:
        return out                                  # git aborts empty messages
    summary = lines[0]

    if RX["autosquash"].match(summary):
        if in_range:
            find("H040", "squash this into its target before it leaves the clone")
        return out
    if RX["passthru"].match(summary):
        return out

    if len(summary) > MAX_SUMMARY:
        find("H002", f"summary is {len(summary)} characters, limit {MAX_SUMMARY}")
    if len(lines) > 1 and lines[1]:
        find("H003", "line 2 is not blank - the summary wrapped or the body has no gap")

    m = RX["summary"].match(summary)
    if not m:
        find("H001", "expected <type>(<scope>)[!]: <summary>")
        return out
    typ, scope, bang, desc = m["type"], m["scope"], bool(m["bang"]), m["desc"]
    fw = RX["first_word"].match(desc)
    first = fw.group(0).lower() if fw else ""

    if desc[0].isupper():
        find("H005", "summary starts with a capital")
    if desc.endswith("."):
        find("H005", "summary ends with a period")
    if RX["wip"].search(desc):
        find("H006", "'wip' is not a summary - say what state it is in")
    if " + " in desc:
        find("H007", "' + ' joins two changes: make two commits")

    if typ in CONTENT_TYPES:
        _check_content(typ, scope, first, desc, paths, tree, find)
    elif typ in MACHINERY_TYPES:
        # The first word is free here, so it is judged here (H006, H008);
        # content verbs are a closed list and H011 judges them instead.
        if first in FILLER_FIRST:
            find("H006", f"opens with filler {first!r} - name the change")
        if first in IRREGULAR_PAST or (RX["ed_ing"].match(first)
                                       and first not in ED_ING_IMPERATIVES):
            find("H008", f"{first!r} is not imperative - 'If applied, this commit will ...'")
        _check_machinery(scope, paths, tree, find)
    else:
        find("H004", f"unknown type {typ!r}; content: {', '.join(CONTENT_TYPES)}; "
                     f"machinery: {', '.join(MACHINERY_TYPES)}")

    body, trailers = split_body(lines)
    needs_body = (typ in BODY_TYPES or bang
                  or (typ in CONTENT_TYPES and first in BODY_VERBS))
    if needs_body and not body:
        why = "'!'" if bang else (repr(first) if typ in CONTENT_TYPES else typ)
        find("H030", f"{why} needs a body: why, then what was verified")

    breaking = any(RX["trailer"].match(t)["key"] in BREAKING_KEYS
                   for t in trailers if RX["trailer"].match(t))
    if bang and not breaking:
        find("H031", "'!' without a BREAKING CHANGE: footer saying what to update")
    if breaking and not bang:
        find("H031", "BREAKING CHANGE: footer without '!' after the scope")

    for i, ln in enumerate(lines[2:], start=3):
        if len(ln) > MAX_BODY and ln in body and "://" not in ln:
            find("H032", f"line {i} is {len(ln)} characters, limit {MAX_BODY}")
    return out


def _check_content(typ, scope, verb, desc, paths, tree, find) -> None:
    known = courses_in(tree) | courses_in(paths or [])
    if not scope:
        find("H010", f"{typ} needs the course as scope (just courses)")
    elif scope not in known:
        find("H010", f"no course {scope!r} (just courses)")

    if verb not in CONTENT_VERBS:
        find("H011", f"{verb or desc.split()[0]!r} is not a content verb; "
                     f"use one of: {', '.join(CONTENT_VERBS)}")
    elif verb == "draft" and not RX["draft_open"].search(desc):
        find("H013", "draft must end with what is open: draft ps_09 p_01 (step 3 open)")

    if paths and scope:
        want = f"{typ}({scope})"
        stray = [p for p in paths if where(p).content != want]
        for p in stray[:10]:
            got = where(p).content or where(p).component
            find("H012", f"{p} is {got}, not {want} - split the commit")
        if len(stray) > 10:
            find("H012", f"... and {len(stray) - 10} more paths outside {want}")


def _check_machinery(scope, paths, tree, find) -> None:
    if not scope:
        find("H020", "machinery needs a component as scope (just commit-scopes)")
    elif paths:
        here = components_in(paths)
        if scope not in here:
            find("H020", f"scope {scope!r} names no changed path; "
                         f"changed: {', '.join(sorted(here))}")
    elif scope not in components_in(tree):
        find("H020", f"no component {scope!r} (just commit-scopes)")

    if paths and scope != COURSEWORK:
        inside = [p for p in paths if p.split("/")[0] == "01_coursework"]
        for p in inside[:10]:
            find("H021", f"{p} is coursework - use a content type, or scope "
                         f"{COURSEWORK} for a mechanical cross-course change")
        if len(inside) > 10:
            find("H021", f"... and {len(inside) - 10} more 01_coursework/ paths")


# --------------------------------------------------------------------------- #
# modes
# --------------------------------------------------------------------------- #

def _print(findings: list[Finding], indent: str = "") -> None:
    for f in findings:
        print(f"{indent}{f.rule_id}  {f.message}")


def run_message(path: Path) -> int:
    lines = clean(path.read_text())
    paths = staged_paths() or None          # message-only amend: nothing staged
    findings = check(lines, paths, tracked_paths())
    _print(findings)
    if findings:
        print(f"\n{len(findings)} finding(s) - see .gitmessage for the rules")
    return 1 if findings else 0


def run_range(revs: list[str]) -> int:
    base = cutoff()
    # ^base goes first: a later --not in revs must not flip it.
    shas = git("rev-list", "--reverse", "--no-merges", f"^{base}",
               *(revs or ["HEAD"])).split()
    tree = tracked_paths()
    bad = total = 0
    for sha in shas:
        lines = clean(git("log", "-1", "--format=%B", sha))
        findings = check(lines, commit_paths(sha), tree, in_range=True)
        total += len(findings)
        if findings:
            bad += 1
            print(f"{sha[:7]} {lines[0] if lines else '(empty message)'}")
            _print(findings, indent="  ")
    print(f"\n{total} finding(s) in {bad} of {len(shas)} commit(s) after {base[:7]}")
    return 1 if total else 0


def run_scopes() -> int:
    tree = tracked_paths()
    dirs = {}
    for p in tree:
        w = where(p)
        if w.course:
            dirs.setdefault(w.course, set()).add("/".join(p.split("/")[:3]))
    print(f"courses   {'|'.join(CONTENT_TYPES)}(<course>)")
    for c in sorted(dirs, key=lambda c: sorted(dirs[c])):
        note = "  AMBIGUOUS" if len(dirs[c]) > 1 else ""
        print(f"  {c:28} {', '.join(sorted(dirs[c]))}{note}")
    print(f"\ncomponents   {'|'.join(MACHINERY_TYPES)}(<component>)")
    for comp in sorted(components_in(tree)):
        print(f"  {comp}")
    return 0


def derive(paths: list[str]) -> tuple[str, str]:
    """(line-1 prefix, comment) for a set of staged paths; either may be empty."""
    ws = [where(p) for p in paths]
    content = sorted({w.content for w in ws if w.content})
    loose = [w for w in ws if not w.content]
    if content and loose:
        return "", "# staged paths mix coursework and machinery - split the commit (H012, H021)"
    if content:
        if len(content) == 1:
            return f"{content[0]}: ", ""
        return "", f"# staged paths span {', '.join(content)} - split the commit (H012)"
    comps = sorted({w.component for w in ws})
    if len(comps) == 1:
        return f"({comps[0]}): ", ""            # the type is a decision; leave it
    return "", f"# staged components: {', '.join(comps)} - the scope names the main one (H020)"


def run_prepare(path: Path, source: str) -> int:
    """Prefill line 1 from the staged paths. Never fails a commit."""
    if source not in ("", "template"):
        return 0            # -m/-F, merge, squash, amend: a message already exists
    paths = staged_paths()
    if not paths:
        return 0
    head, note = derive(paths)
    lines = path.read_text().split("\n")
    if head:
        if lines and not lines[0].strip():
            lines[0] = head
        else:
            lines.insert(0, head)
    if note:
        lines.insert(1, note)
    path.write_text("\n".join(lines))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="validate commit messages against .gitmessage")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--message-file", type=Path, metavar="F",
                      help="check one message against the staged paths (commit-msg)")
    mode.add_argument("--scopes", action="store_true",
                      help="print the courses and components the tree admits")
    mode.add_argument("--prepare", type=Path, metavar="F",
                      help="prefill type(scope) into F from the staged paths "
                           "(prepare-commit-msg)")
    ap.add_argument("--source", default="",
                    help="with --prepare: git's message source ($2 of the hook)")
    ap.add_argument("revs", nargs="*",
                    help="rev-list arguments; default: every commit after the cutoff")
    args = ap.parse_args(argv)

    check_schema()

    if args.message_file:
        return run_message(args.message_file)
    if args.scopes:
        return run_scopes()
    if args.prepare:
        return run_prepare(args.prepare, args.source)
    return run_range(args.revs)


if __name__ == "__main__":
    raise SystemExit(main())
