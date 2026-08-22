#!/usr/bin/env python3

"""
build_day_files.py — extract referenced problems from Analysis 2 problem sets
and emit per-day org files for exam prep.

Two stages, one script:
  STAGE 1  parse ps_XX/ps_XX.org  -> problem_bank.org   (the lookup format)
  STAGE 2  parse the plan         -> {day: [PSxx Pyy]}  -> NN_day.org files

The day files are filtered views of the bank. If the parser mis-reads a few
statements, hand-fix them ONCE in problem_bank.org, then regenerate the day
files with --use-bank (skips PS parsing entirely).

Examples
--------
# verify extraction WITHOUT writing anything (do this first):
python build_day_files.py --plan analysis2_plan.org --out-dir days --dry-run

# normal run (build bank from PS dir, then day files; never overwrites):
python build_day_files.py --plan analysis2_plan.org --out-dir days

# regenerate day files from a hand-corrected bank:
python build_day_files.py --plan analysis2_plan.org --out-dir days --use-bank
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

# Default; override with --ps-dir.
DEFAULT_PS_DIR = Path(
    "/Users/ziro2173/personal/mfds/01_coursework/"
    "02_semester/01_analysis_ii/02_problems"
)

# ──────────────────────────────────────────────────────────────────────────
# PS-org parsing — tuned to your actual file layout (ps_02, ps_14):
#
#     * Problem N :tag:tag:            <- level-1 heading, one star
#     ** Task
#     #+begin_quote
#     ...statement (LaTeX preserved)...
#     #+end_quote
#     ** Solution
#     *** (a) ... etc.
#
#   * STATEMENT = the verbatim contents of the begin_quote block under
#     ** Task (NOT the Solution; ps_14 P2's Solution also contains a quote,
#     which is correctly ignored because the search is bounded to the Task
#     section).
#   * PART LABELS = "(a)", "(b)", ... that begin a line inside the Task quote.
#     Line-anchored so inline math like $g(x)=0$ or $f(a)$ is not miscounted.
#   * Your worked SOLUTION is intentionally discarded; the generated entry
#     gets an empty "Grasped" scaffold per the target format. (To carry your
#     solutions over instead, return the Solution section in _extract_task.)
#
# If a file ever uses a different problem keyword or heading level, adjust
# PROBLEM_HEADING_RE (currently: level-1 "* Problem N" / "* Aufgabe N").
# ──────────────────────────────────────────────────────────────────────────
PROBLEM_HEADING_RE = re.compile(r"^\*\s+(?:Problem|Aufgabe|Exercise)\s+0*(\d+)\b", re.I)

# Part label: "(a)".."(h)" at the start of a line (enumeration, not math).
PART_RE = re.compile(r"(?m)^\s*\(([a-h])\)")

# Plan: day headings, e.g.  ** Day 1 — Mon Jun 29 · Gradient ... :build:drill:
DAY_RE = re.compile(r"^\*+\s+Day\s+(?P<num>\d+)\s*[—–-]?\s*(?P<title>.*)$")

# Plan: problem references. Captures "PS12" and the following P-run.
# The P-run extends only across separators FOLLOWED by a digit, so prose
# em-dashes (—, U+2014) terminate it, while en-dash ranges (–, U+2013) and
# / + , lists are captured. "PS13 P3 + PS14 P1" -> two separate matches.
PS_RE = re.compile(r"PS\s*0*(\d+)\s+(P0*\d+(?:\s*[-–/+,]\s*P?0*\d+)*)")


@dataclass
class Problem:
    ps: int
    p: int
    statement: str
    parts: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"PS{self.ps:02d} P{self.p:02d}"


# ── parsing: PS org files ──────────────────────────────────────────────────
def _strip_blank_lines(s: str) -> str:
    lines = s.split("\n")
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


def _parts_from(s: str) -> list[str]:
    return sorted(set(PART_RE.findall(s)))


def _extract_task(block: list[str]) -> str:
    """Given one problem's lines (heading -> next top-level heading), return
    the verbatim statement: the begin_quote contents under ** Task."""
    task_i = next(
        (i for i, ln in enumerate(block) if re.match(r"^\*\*\s+Task\b", ln, re.I)),
        None,
    )
    if task_i is None:
        # Fallback: body down to the first sub-heading.
        body = []
        for ln in block[1:]:
            if re.match(r"^\*+\s", ln):
                break
            body.append(ln)
        return _strip_blank_lines("\n".join(body))

    # Bound the Task section at the next **-level heading (** Solution).
    end = len(block)
    for i in range(task_i + 1, len(block)):
        if re.match(r"^\*\*+\s", block[i]):
            end = i
            break
    section = "\n".join(block[task_i + 1 : end])

    qm = re.search(r"(?is)#\+begin_quote\s*\n(.*?)\n#\+end_quote", section)
    return _strip_blank_lines(qm.group(1) if qm else section)


def parse_ps_org_file(path: Path, ps: int) -> dict[int, Problem]:
    lines = path.read_text(encoding="utf-8").splitlines()

    # Level-1 problem headings ("* Problem N"); record their line numbers.
    prob_heads = [
        (i, int(m.group(1)))
        for i, ln in enumerate(lines)
        if (m := PROBLEM_HEADING_RE.match(ln))
    ]
    if not prob_heads:
        return {}

    # All level-1 headings (incl. "* Errors/Typos") bound each problem block.
    top_heads = [i for i, ln in enumerate(lines) if re.match(r"^\*\s", ln)]

    out: dict[int, Problem] = {}
    for line_i, num in prob_heads:
        end = next((h for h in top_heads if h > line_i), len(lines))
        block = lines[line_i:end]
        statement = _extract_task(block)
        out[num] = Problem(ps, num, statement, _parts_from(statement))
    return out


def build_bank_from_ps_dir(ps_dir: Path) -> dict[tuple[int, int], Problem]:
    problems: dict[tuple[int, int], Problem] = {}
    for d in sorted(ps_dir.glob("ps_*")):
        if not d.is_dir():
            continue
        m = re.match(r"ps_0*(\d+)$", d.name)
        if not m:
            continue
        ps = int(m.group(1))
        org = d / f"{d.name}.org"
        if not org.exists():
            print(f"  ! {d.name}: no {org.name} — its problems will be stubs")
            continue
        pset = parse_ps_org_file(org, ps)
        if not pset:
            print(f"  ! {d.name}: no headings matched PROBLEM_HEADING_RE")
        for p, prob in pset.items():
            problems[(ps, p)] = prob
    return problems


# ── parsing: bank round-trip (for --use-bank) ──────────────────────────────
def parse_bank_org(path: Path) -> dict[tuple[int, int], Problem]:
    text = path.read_text(encoding="utf-8")
    out: dict[tuple[int, int], Problem] = {}
    for block in re.split(r"(?m)^(?=\* PS\d+ P\d+)", text):
        hm = re.match(r"^\* PS(\d+) P(\d+)", block)
        if not hm:
            continue
        ps, p = int(hm.group(1)), int(hm.group(2))
        qm = re.search(r"(?is)#\+begin_quote\s*\n(.*?)\n#\+end_quote", block)
        stmt = qm.group(1).strip() if qm else ""
        out[(ps, p)] = Problem(ps, p, stmt, _parts_from(stmt))
    return out


# ── parsing: the plan ──────────────────────────────────────────────────────
def _expand_pnums(run: str) -> list[int]:
    """'P1' -> [1]; 'P1–P4' -> [1,2,3,4]; 'P2/P4' -> [2,4]; 'P3+P4' -> [3,4]."""
    tokens = re.findall(r"\d+|[-–/+,]", run)
    out: list[int] = []
    j = 0
    while j < len(tokens):
        t = tokens[j]
        if t.isdigit():
            out.append(int(t))
            j += 1
        elif t in ("-", "–"):  # range: connect prev number to next
            if out and j + 1 < len(tokens) and tokens[j + 1].isdigit():
                out.extend(range(out[-1] + 1, int(tokens[j + 1]) + 1))
                j += 2
            else:
                j += 1
        else:  # / + ,  -> discrete separators
            j += 1
    seen, res = set(), []
    for n in out:
        if n not in seen:
            seen.add(n)
            res.append(n)
    return res


def _refs_in_line(line: str) -> list[tuple[int, int]]:
    refs = []
    for m in PS_RE.finditer(line):
        ps = int(m.group(1))
        refs += [(ps, p) for p in _expand_pnums(m.group(2))]
    return refs


def _clean_day_title(t: str) -> str:
    t = t.split("⚠")[0]                       # drop warning annotations
    t = re.sub(r"\s*:[\w:]+:", "", t)          # drop org tag clusters
    return t.strip()


def parse_plan(path: Path) -> list[tuple[int, str, list[tuple[int, int]]]]:
    days: list[tuple[int, str, list[tuple[int, int]]]] = []
    cur: tuple[int, str, list[tuple[int, int]]] | None = None
    for ln in path.read_text(encoding="utf-8").splitlines():
        dm = DAY_RE.match(ln)
        if dm:
            if cur:
                days.append(cur)
            cur = (int(dm.group("num")), _clean_day_title(dm.group("title")), [])
        elif cur is not None:
            for ref in _refs_in_line(ln):
                if ref not in cur[2]:          # per-day dedup, preserve order
                    cur[2].append(ref)
    if cur:
        days.append(cur)
    return days


# ── output formatting ──────────────────────────────────────────────────────
HEADER_TEMPLATE = r"""#+title: @TITLE@
#+author: Erik An
#+email: obluda2173@gmail.com
#+date: <@DATE@>
#+lastmod: <@LASTMOD@>
#+latex: \newpage
#+latex_header: \setlength{\parindent}{0pt}
#+latex_header: \setlength{\parskip}{1em}
#+latex_header: \usepackage{amsmath}
#+latex_header: \usepackage{amssymb}
#+latex_header: \usepackage{mathtools}
#+latex_header: \usepackage{amsthm}
#+latex_header: \usepackage[margin=1in]{geometry}
#+options: num:t tags:nil
#+property: header-args :eval never-export
#+startup: overview latexpreview inlineimages
#+columns: %50ITEM(Item) %8LECTURE_REF(Lecture) %34CUSTOM_ID(ID)

"""

BANK_HEADER = r"""#+title: Analysis 2 — Problem Bank
#+author: Erik An
#+options: num:nil tags:nil
#+startup: overview latexpreview

"""


def day_header(title: str) -> str:
    return (
        HEADER_TEMPLATE.replace("@TITLE@", title)
        .replace("@DATE@", date.today().isoformat())
        .replace("@LASTMOD@", datetime.now().strftime("%Y-%m-%d %H:%M"))
    )


def format_problem(prob: Problem) -> str:
    out = [
        f"* {prob.key}",
        "** Task",
        "#+begin_quote",
        prob.statement.strip(),
        "#+end_quote",
        "",
        "** Solution",
        "",
    ]
    if prob.parts:
        for label in prob.parts:
            out += [f"*** ({label})", "", "**** Grasped", ""]
    else:
        out += ["*** Grasped", ""]
    return "\n".join(out).rstrip() + "\n"


def write_bank(problems: dict[tuple[int, int], Problem], path: Path) -> None:
    body = "\n".join(format_problem(problems[k]) for k in sorted(problems))
    path.write_text(BANK_HEADER + body, encoding="utf-8")
    print(f"  wrote {path.name} ({len(problems)} problems)")


def write_day_files(
    days, problems, out_dir: Path, force: bool, dry_run: bool
) -> None:
    if not dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)

    missing = []
    for num, title, refs in days:
        fname = out_dir / f"{num:02d}_day.org"

        if dry_run:
            print(f"\nDay {num} — {title}")
            print(f"  -> {fname.name}: {len(refs)} problems")
            for ps, p in refs:
                tag = "" if (ps, p) in problems else "   [MISSING]"
                print(f"     PS{ps:02d} P{p:02d}{tag}")
            continue

        if fname.exists() and not force:
            print(f"  skip {fname.name} (exists; pass --force to overwrite)")
            continue

        chunks = [day_header(f"Day {num} — {title}")]
        for ps, p in refs:
            prob = problems.get((ps, p))
            if prob is None:
                prob = Problem(
                    ps, p,
                    f"[NOT FOUND — check ps_{ps:02d}/ps_{ps:02d}.org "
                    f"or PROBLEM_HEADING_RE]",
                    [],
                )
                missing.append((num, ps, p))
            chunks.append(format_problem(prob))
        fname.write_text("\n".join(chunks), encoding="utf-8")
        print(f"  wrote {fname.name} ({len(refs)} problems)")

    if missing and not dry_run:
        print("\nMissing (emitted as stubs):")
        for num, ps, p in missing:
            print(f"  Day {num}: PS{ps:02d} P{p:02d}")


# ── entry point ────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--plan", required=True, type=Path,
                    help="path to the plan .org file (day headings + PSxx Pyy refs)")
    ap.add_argument("--out-dir", required=True, type=Path,
                    help="directory to write NN_day.org files into")
    ap.add_argument("--ps-dir", type=Path, default=DEFAULT_PS_DIR,
                    help="directory containing ps_01 ... ps_14")
    ap.add_argument("--bank", type=Path, default=None,
                    help="bank file path (default: <out-dir>/problem_bank.org)")
    ap.add_argument("--use-bank", action="store_true",
                    help="load problems from an existing (hand-corrected) bank "
                         "instead of parsing the PS directory")
    ap.add_argument("--force", action="store_true",
                    help="overwrite day files that already exist")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the per-day resolved refs and exit; writes nothing")
    args = ap.parse_args()

    if not args.plan.exists():
        print(f"plan not found: {args.plan}", file=sys.stderr)
        return 1

    bank_path = args.bank or (args.out_dir / "problem_bank.org")

    # Load problems.
    if args.use_bank:
        if not bank_path.exists():
            print(f"--use-bank set but {bank_path} not found", file=sys.stderr)
            return 1
        print(f"Loading problems from bank: {bank_path}")
        problems = parse_bank_org(bank_path)
        print(f"  loaded {len(problems)} problems")
    else:
        if not args.ps_dir.exists():
            print(f"ps-dir not found: {args.ps_dir}", file=sys.stderr)
            return 1
        print(f"Parsing problem sets in: {args.ps_dir}")
        problems = build_bank_from_ps_dir(args.ps_dir)
        print(f"  parsed {len(problems)} problems total")

    # Parse the plan.
    print(f"\nParsing plan: {args.plan}")
    days = parse_plan(args.plan)
    print(f"  found {len(days)} days")

    # Write bank (skip in dry-run and in use-bank mode).
    if not args.dry_run and not args.use_bank:
        args.out_dir.mkdir(parents=True, exist_ok=True)
        write_bank(problems, bank_path)

    # Write / preview day files.
    print()
    write_day_files(days, problems, args.out_dir, args.force, args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
