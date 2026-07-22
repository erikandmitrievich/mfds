#!/usr/bin/env python3
"""Repository analytics for the study repo.

Third companion to STRUCTURE.org / validate_structure.py / justfile. Those two
declare the layout and enforce it; this one measures it. To keep the three from
describing different repositories, it:

  * reads the same file set the tree snapshot does -- ``git ls-files`` -- so
    untracked audio, build artefacts and editor droppings never leak into the
    numbers, and the size figure is the size of what is actually committed;
  * classifies paths with the validator's own vocabulary (00_global vs
    01_coursework, the 01_material / 02_problems / 03_exams split, the exam
    stage names), so a metric never silently drifts from a rule;
  * reuses the provenance check (#+model:/#+prompt:/#+date:) that
    validate_structure.py runs under --content, and reports coverage on
    01_extracted/ build products -- the one repo-specific invariant that a name
    check cannot express.

Run:
    just stats
    python3 repository_stats.py [--root DIR] [--no-git] [--top N]
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

# --------------------------------------------------------------------------- #
# vocabulary shared with validate_structure.py / STRUCTURE.org
# --------------------------------------------------------------------------- #

COURSEWORK = "01_coursework"
GLOBAL     = "00_global"
LLM_RULES  = "_llm_rules"
SCRIPTS    = "scripts"

# exam pipeline stages, in order (see validate_structure._STAGES)
EXAM_STAGES = ("00_resources", "01_extracted", "02_plan",
               "03_preparation", "04_revision")
STAGE_LABEL = {
    "00_resources":   "resources",
    "01_extracted":   "extracted",
    "02_plan":        "plan",
    "03_preparation": "preparation",
    "04_revision":    "revision",
}
PROVENANCE_KEYS = ("#+model:", "#+prompt:", "#+date:")

# directories the git fallback walk ignores; aligned with the validator
IGNORE_DIRS = {".git", "__pycache__", "node_modules", ".venv",
               ".ipynb_checkpoints", ".obsidian"}

# opened but not parsed for prose/math; bytes excluded from the size figure
BINARY_EXT = {".pdf", ".png", ".jpg", ".jpeg", ".svg", ".gif", ".webp",
              ".m4a", ".mp3", ".wav", ".mp4", ".mov", ".zip", ".tar", ".gz"}

LANG_MAP = {
    "jupyter-python": "Python", "python": "Python",
    "julia": "Julia",
    "bash": "Shell", "sh": "Shell", "shell": "Shell",
    "c++": "C++", "cpp": "C++", "c": "C",
    "latex": "LaTeX",
    "r": "R",
    "emacs-lisp": "Elisp", "elisp": "Elisp",
    "sql": "SQL",
    "javascript": "JavaScript", "js": "JavaScript",
    "typescript": "TypeScript", "ts": "TypeScript",
    "html": "HTML", "css": "CSS",
    "rust": "Rust", "haskell": "Haskell", "ocaml": "OCaml",
    "scheme": "Scheme", "racket": "Racket",
    "gnuplot": "Gnuplot", "dot": "Graphviz",
}

MATH_ENVS = {
    "equation", "equation*", "align", "align*", "gather", "gather*",
    "multline", "multline*", "flalign", "flalign*", "eqnarray", "eqnarray*",
    "split", "cases", "matrix", "pmatrix", "bmatrix", "vmatrix", "Vmatrix",
    "array", "aligned", "gathered", "smallmatrix",
}
THEOREM_ENVS = {
    "theorem", "lemma", "proposition", "corollary", "conjecture",
    "definition", "example", "examples", "remark", "remarks", "note",
    "proof", "exercise", "problem", "solution", "claim",
}

# --- regexes (compiled once) --------------------------------------------- #

RE_INLINE_MATH   = re.compile(r"(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)")
RE_DISPLAY_DOLLAR = re.compile(r"\$\$(.+?)\$\$")
RE_DISPLAY_BRACKET = re.compile(r"\\\[")
RE_INLINE_PAREN  = re.compile(r"\\\(")
RE_BEGIN_ENV     = re.compile(r"\\begin\{(\w+\*?)\}")
RE_END_ENV       = re.compile(r"\\end\{(\w+\*?)\}")
RE_HEADING       = re.compile(r"^(\*+)\s")
RE_TAG_TAIL      = re.compile(r"\s(:(?:[A-Za-z0-9_@#%]+:)+)\s*$")   # trailing :a:b:
RE_LINK          = re.compile(r"\[\[([^\]]+)\]")
RE_TIMESTAMP     = re.compile(r"[<\[]\d{4}-\d{2}-\d{2}")
RE_FOOTNOTE      = re.compile(r"\[fn:([^\]]+)\]")
RE_TABLE_ROW     = re.compile(r"^\s*\|")
RE_PROPERTY      = re.compile(r"^\s*:([A-Za-z][A-Za-z0-9_]*):\s")
RE_CITE          = re.compile(r"\[cite[:/]")
RE_LATEX_CMD     = re.compile(r"\\([a-zA-Z]+)")
RE_WHOLE_DISPLAY = re.compile(r"^\$\$.*\$\$$")
RE_DRAWER_OPEN   = re.compile(r"^:([A-Za-z][A-Za-z0-9_]*):$")

RE_LEC = re.compile(r"^lec_\d{2}(-\d{2})?\.org$")
RE_CH  = re.compile(r"^(ch|app)_[a-z0-9_]+\.org$")
RE_DAY = re.compile(r"^day_\d{2}\.org$")


# --------------------------------------------------------------------------- #
# metrics container
# --------------------------------------------------------------------------- #

def new_metrics():
    return {
        # file counts
        "org_files": 0, "py_files": 0, "jl_files": 0, "other_files": 0,
        "size_bytes": 0,                      # text files only
        # prose (authored prose lines only -- see _parse_org)
        "prose_words": 0, "prose_lines": 0,
        # code (lang -> lines), from src blocks and standalone .py/.jl
        "code_lines": defaultdict(int), "src_blocks": defaultdict(int),
        # math
        "inline_math": 0, "display_math": 0, "math_lines": 0,
        "math_envs": defaultdict(int),
        "theorem_envs": defaultdict(int),
        "other_envs": defaultdict(int),
        "latex_cmds": defaultdict(int),
        # org structure
        "headings": defaultdict(int), "max_depth": 0,
        "tags": defaultdict(int), "properties": defaultdict(int),
        "links": 0, "timestamps": 0, "footnotes": 0, "citations": 0,
        "table_rows": 0, "drawers": 0,
        "todo": 0, "done": 0,
        # coursework-area extras
        "lectures": 0, "chapters": 0, "material_other": 0,
        "problem_sets": set(),
        "extracted": 0, "extracted_with_prov": 0,
        "day_files": 0, "plans": 0, "revision_files": 0, "resource_files": 0,
        "stages": set(),
    }


def merge(dst, src):
    for k, v in src.items():
        if isinstance(v, set):
            dst[k] |= v
        elif isinstance(v, defaultdict):
            for kk, vv in v.items():
                dst[k][kk] += vv
        elif k == "max_depth":
            dst[k] = max(dst[k], v)
        else:
            dst[k] += v


# --------------------------------------------------------------------------- #
# parsing
# --------------------------------------------------------------------------- #

def parse_org(lines, m):
    """Fill content metrics for one .org file into ``m``."""
    in_src = False
    lang = None
    in_env = False
    env = None
    in_drawer = False

    for line in lines:
        stripped = line.strip()

        # -- drawers (:PROPERTIES: ... :END:) ------------------------------ #
        if in_drawer:
            if stripped == ":END:":
                in_drawer = False
                continue
            pm = RE_PROPERTY.match(line)
            if pm:
                m["properties"][pm.group(1)] += 1
            continue
        dm = RE_DRAWER_OPEN.match(stripped)
        if dm and dm.group(1) != "END" and not in_src:
            in_drawer = True
            m["drawers"] += 1
            continue

        # -- source blocks ------------------------------------------------- #
        low = stripped.lower()
        if low.startswith("#+begin_src"):
            in_src = True
            parts = stripped.split()
            raw = parts[1].lower() if len(parts) > 1 else "unknown"
            lang = LANG_MAP.get(raw, raw)
            m["src_blocks"][lang] += 1
            continue
        if low.startswith("#+end_src"):
            in_src = False
            lang = None
            continue
        if in_src:
            if stripped and not stripped.startswith("#"):
                m["code_lines"][lang] += 1
            continue

        # -- LaTeX environments ------------------------------------------- #
        was_in_env = in_env
        begin = RE_BEGIN_ENV.search(line)
        if begin and not in_env:
            in_env = True
            env = begin.group(1)
            if env in MATH_ENVS:
                m["math_envs"][env] += 1
                m["display_math"] += 1
            elif env in THEOREM_ENVS:
                m["theorem_envs"][env] += 1
            else:
                m["other_envs"][env] += 1
        if in_env and env in MATH_ENVS:
            m["math_lines"] += 1
        end = RE_END_ENV.search(line)
        if end and in_env and end.group(1) == env:
            in_env = False
            env = None

        # -- inline / display math outside environments ------------------- #
        if not in_env:
            m["inline_math"] += len(RE_INLINE_MATH.findall(line))
            m["inline_math"] += len(RE_INLINE_PAREN.findall(line))
            m["display_math"] += len(RE_DISPLAY_DOLLAR.findall(line))
            m["display_math"] += len(RE_DISPLAY_BRACKET.findall(line))

        for cmd in RE_LATEX_CMD.findall(line):
            m["latex_cmds"][cmd] += 1

        # -- headings, tags, tasks ---------------------------------------- #
        hm = RE_HEADING.match(line)
        if hm:
            depth = len(hm.group(1))
            m["headings"][depth] += 1
            m["max_depth"] = max(m["max_depth"], depth)
            tm = RE_TAG_TAIL.search(line.rstrip())
            if tm:
                for t in tm.group(1).strip(":").split(":"):
                    if t:
                        m["tags"][t] += 1
            for kw, key in (("TODO", "todo"), ("DONE", "done")):
                if f" {kw} " in line or line.rstrip().endswith(f" {kw}"):
                    m[key] += 1

        # -- links / timestamps / footnotes / citations / tables ---------- #
        m["links"]      += len(RE_LINK.findall(line))
        m["timestamps"] += len(RE_TIMESTAMP.findall(line))
        m["footnotes"]  += len(RE_FOOTNOTE.findall(line))
        m["citations"]  += len(RE_CITE.findall(line))
        if RE_TABLE_ROW.match(line):
            m["table_rows"] += 1

        # -- prose: authored prose only ----------------------------------- #
        # excludes headings, tables, keyword/comment lines, drawer lines,
        # whole-line display math, and anything inside a math environment.
        env_line = was_in_env or begin or end
        if (stripped and not env_line and not hm
                and not stripped.startswith("#")
                and not stripped.startswith("|")
                and not stripped.startswith(":")
                and stripped != "$$"
                and not RE_WHOLE_DISPLAY.match(stripped)):
            m["prose_lines"] += 1
            m["prose_words"] += len(line.split())


def head_has_provenance(lines):
    head = [ln for ln in lines[:15]]
    present = {k for ln in head for k in PROVENANCE_KEYS if ln.startswith(k)}
    return all(k in present for k in PROVENANCE_KEYS)


def count_code_file(lines):
    return sum(1 for l in lines
               if l.strip() and not l.strip().startswith("#"))


# --------------------------------------------------------------------------- #
# classification
# --------------------------------------------------------------------------- #

def classify(parts):
    """Map a repo-relative path to (bucket, area, extra).

    bucket : ("course", sem, course) | ("infra", name) | ("meta",)
    area   : "material" | "problems" | "exams" | None   (course only)
    extra  : dict with area-specific facts
    """
    if parts and parts[0] == GLOBAL:
        if len(parts) > 1 and parts[1] == LLM_RULES:
            return ("infra", "rules"), None, {}
        if len(parts) > 1 and parts[1] == SCRIPTS:
            return ("infra", "scripts"), None, {}
        return ("infra", "other"), None, {}

    if parts and parts[0] == COURSEWORK and len(parts) >= 4:
        sem, course = parts[1], parts[2]
        after = parts[3:]
        area, extra = None, {}
        a0 = after[0]
        if a0 == "01_material":
            area = "material"
            name = after[-1]
            if RE_LEC.match(name):
                extra["kind"] = "lecture"
            elif RE_CH.match(name):
                extra["kind"] = "chapter"
            else:
                extra["kind"] = "material_other"
        elif a0 == "02_problems":
            area = "problems"
            if len(after) > 1:
                extra["ps"] = after[1]
        elif a0 == "03_exams":
            area = "exams"
            stage = next((p for p in after[1:] if p in EXAM_STAGES), None)
            extra["stage"] = stage
            extra["name"] = after[-1]
        return ("course", sem, course), area, extra

    return ("meta",), None, {}


# --------------------------------------------------------------------------- #
# analyzer
# --------------------------------------------------------------------------- #

class RepoStats:
    def __init__(self, root: Path):
        self.root = root
        self.courses = defaultdict(lambda: defaultdict(new_metrics))
        self.infra = defaultdict(new_metrics)        # "rules"/"scripts"/"other"
        self.meta = new_metrics()

    def analyze(self, path: Path):
        try:
            rel = path.relative_to(self.root)
        except ValueError:
            return
        parts = rel.parts
        ext = path.suffix.lower()

        bucket, area, extra = classify(parts)
        if bucket[0] == "course":
            target = self.courses[bucket[1]][bucket[2]]
        elif bucket[0] == "infra":
            target = self.infra[bucket[1]]
        else:
            target = self.meta

        lines = None
        if ext not in BINARY_EXT:
            try:
                lines = path.read_text(encoding="utf-8", errors="ignore").splitlines(keepends=True)
                target["size_bytes"] += path.stat().st_size
            except OSError:
                lines = None

        # file-type counters
        if ext == ".org":
            target["org_files"] += 1
        elif ext == ".py":
            target["py_files"] += 1
            if lines:
                target["code_lines"]["Python"] += count_code_file(lines)
        elif ext == ".jl":
            target["jl_files"] += 1
            if lines:
                target["code_lines"]["Julia"] += count_code_file(lines)
        else:
            target["other_files"] += 1

        # coursework area extras
        if area == "material" and ext == ".org":
            kind = extra.get("kind")
            target["lectures"] += kind == "lecture"
            target["chapters"] += kind == "chapter"
            target["material_other"] += kind == "material_other"
        elif area == "problems":
            if extra.get("ps"):
                target["problem_sets"].add(extra["ps"])
        elif area == "exams":
            stage = extra.get("stage")
            if stage:
                target["stages"].add(STAGE_LABEL[stage])
            if ext == ".org":
                if stage == "01_extracted":
                    target["extracted"] += 1
                    if lines and head_has_provenance(lines):
                        target["extracted_with_prov"] += 1
                elif stage == "03_preparation" and RE_DAY.match(extra.get("name", "")):
                    target["day_files"] += 1
                elif stage == "02_plan":
                    target["plans"] += 1
                elif stage == "04_revision":
                    target["revision_files"] += 1
            if stage == "00_resources":
                target["resource_files"] += 1

        if ext == ".org" and lines is not None:
            parse_org(lines, target)


# --------------------------------------------------------------------------- #
# aggregation helpers
# --------------------------------------------------------------------------- #

def summarize(m):
    files = m["org_files"] + m["py_files"] + m["jl_files"] + m["other_files"]
    return {
        "files": files,
        "org": m["org_files"], "py": m["py_files"],
        "jl": m["jl_files"], "other": m["other_files"],
        "words": m["prose_words"], "prose_lines": m["prose_lines"],
        "code": sum(m["code_lines"].values()),
        "code_breakdown": dict(m["code_lines"]),
        "src_blocks": sum(m["src_blocks"].values()),
        "inline_math": m["inline_math"], "display_math": m["display_math"],
        "math": m["inline_math"] + m["display_math"],
        "math_lines": m["math_lines"],
        "math_envs": dict(m["math_envs"]),
        "theorem_envs": dict(m["theorem_envs"]),
        "other_envs": dict(m["other_envs"]),
        "headings": sum(m["headings"].values()),
        "heading_depth": dict(m["headings"]), "max_depth": m["max_depth"],
        "tags": dict(m["tags"]),
        "links": m["links"], "timestamps": m["timestamps"],
        "footnotes": m["footnotes"], "citations": m["citations"],
        "table_rows": m["table_rows"], "drawers": m["drawers"],
        "done": m["done"], "total_tasks": m["todo"] + m["done"],
        "lectures": m["lectures"], "chapters": m["chapters"],
        "material_other": m["material_other"],
        "problem_sets": len(m["problem_sets"]),
        "extracted": m["extracted"],
        "extracted_with_prov": m["extracted_with_prov"],
        "day_files": m["day_files"], "plans": m["plans"],
        "revision_files": m["revision_files"],
        "stages": m["stages"],
        "size_mb": m["size_bytes"] / (1024 * 1024),
        "top_cmds": dict(sorted(m["latex_cmds"].items(),
                                key=lambda x: -x[1])[:15]),
    }


def add_into(acc, s):
    for k in ("files", "words", "code", "src_blocks", "inline_math",
              "display_math", "math", "math_lines", "headings", "links",
              "timestamps", "footnotes", "citations", "table_rows", "drawers",
              "done", "total_tasks", "lectures", "chapters", "problem_sets",
              "extracted", "extracted_with_prov", "day_files"):
        acc[k] += s[k]
    acc["size_mb"] += s["size_mb"]
    for lang, c in s["code_breakdown"].items():
        acc["code_langs"][lang] += c


# --------------------------------------------------------------------------- #
# reporting
# --------------------------------------------------------------------------- #

W = 78


def _fmt_map(d, sep=", ", top=None, prefix=""):
    items = sorted(d.items(), key=lambda x: -x[1])
    if top:
        items = items[:top]
    return sep.join(f"{prefix}{k}={v}" for k, v in items)


def report(stats: RepoStats, top: int):
    print()
    print("=" * W)
    print("STUDY REPOSITORY ANALYTICS".center(W))
    print("=" * W)

    grand = defaultdict(int, {"size_mb": 0.0, "code_langs": defaultdict(int)})

    for sem in sorted(stats.courses):
        print(f"\n{'-' * W}")
        print(f"  SEMESTER: {sem}")
        print(f"{'-' * W}")
        semacc = defaultdict(int, {"size_mb": 0.0, "code_langs": defaultdict(int)})

        for course in sorted(stats.courses[sem]):
            s = summarize(stats.courses[sem][course])
            print(f"\n  [{course}]")
            print(f"    {'Files:':<26} {s['files']:>6}  "
                  f"(org={s['org']}, py={s['py']}, jl={s['jl']}, other={s['other']})")
            print(f"    {'Prose:':<26} {s['words']:>6,} words  /  {s['prose_lines']:,} lines")

            # math
            print(f"    {'Math (inline/display):':<26} {s['inline_math']:>6,} / {s['display_math']:,}")
            if s["math_envs"]:
                print(f"    {'  Math envs:':<26} {_fmt_map(s['math_envs'])}")
            if s["math_lines"]:
                print(f"    {'  Lines in math envs:':<26} {s['math_lines']:>6,}")

            # code
            if s["code"]:
                print(f"    {'Code lines:':<26} {s['code']:>6,}  ({s['src_blocks']} src blocks)")
                if s["code_breakdown"]:
                    print(f"    {'  Breakdown:':<26} {_fmt_map(s['code_breakdown'])}")

            # structure
            print(f"    {'Headings:':<26} {s['headings']:>6,}  (max depth={s['max_depth']})")
            if s["heading_depth"]:
                hd = ", ".join(f"L{d}={c}" for d, c in sorted(s["heading_depth"].items()))
                print(f"    {'  By depth:':<26} {hd}")

            # material composition
            if s["lectures"] or s["chapters"] or s["material_other"]:
                bits = []
                if s["lectures"]:       bits.append(f"lectures={s['lectures']}")
                if s["chapters"]:       bits.append(f"chapters={s['chapters']}")
                if s["material_other"]: bits.append(f"other={s['material_other']}")
                print(f"    {'Material:':<26} {', '.join(bits)}")

            # problems
            if s["problem_sets"]:
                print(f"    {'Problem sets:':<26} {s['problem_sets']:>6}")

            # exam pipeline
            if s["stages"]:
                order = [STAGE_LABEL[k] for k in EXAM_STAGES]
                present = [x for x in order if x in s["stages"]]
                print(f"    {'Exam stages:':<26} {', '.join(present)}")
                if s["extracted"]:
                    pct = s["extracted_with_prov"] / s["extracted"] * 100
                    print(f"    {'  Extracted products:':<26} {s['extracted']:>6}  "
                          f"(provenance {s['extracted_with_prov']}/{s['extracted']}, {pct:.0f}%)")
                if s["day_files"]:
                    print(f"    {'  Prep day files:':<26} {s['day_files']:>6}")
                if s["revision_files"]:
                    print(f"    {'  Revision files:':<26} {s['revision_files']:>6}")

            # meta counters
            for label, key in (("Links:", "links"), ("Timestamps:", "timestamps"),
                               ("Table rows:", "table_rows"), ("Citations:", "citations"),
                               ("Drawers:", "drawers")):
                if s[key]:
                    print(f"    {label:<26} {s[key]:>6,}")

            if s["tags"]:
                tstr = ", ".join(f":{t}:={c}" for t, c in
                                 sorted(s["tags"].items(), key=lambda x: -x[1])[:top])
                print(f"    {'Top tags:':<26} {tstr}")
            if s["total_tasks"]:
                pct = s["done"] / s["total_tasks"] * 100
                print(f"    {'Tasks (done/total):':<26} {s['done']}/{s['total_tasks']} ({pct:.0f}%)")
            print(f"    {'Size (text):':<26} {s['size_mb']:>6.2f} MB")
            if s["top_cmds"]:
                cmds = ", ".join(f"\\{c}={n}" for c, n in list(s["top_cmds"].items())[:top])
                print(f"    {'Top LaTeX cmds:':<26} {cmds}")

            add_into(semacc, s)

        print(f"\n  {'Semester totals ':-<{W - 2}}")
        _print_totals(semacc, indent=4)
        for k, v in semacc.items():
            if k == "code_langs":
                for lang, c in v.items():
                    grand["code_langs"][lang] += c
            elif k == "size_mb":
                grand["size_mb"] += v
            else:
                grand[k] += v

    # ----- infrastructure (00_global) -- reported, never folded in ------- #
    if any(stats.infra.values()):
        print(f"\n{'-' * W}")
        print("  INFRASTRUCTURE (00_global) -- not counted in coursework totals")
        print(f"{'-' * W}")
        for name in ("rules", "scripts", "other"):
            if name not in stats.infra:
                continue
            s = summarize(stats.infra[name])
            if not s["files"]:
                continue
            label = {"rules": "_llm_rules", "scripts": "scripts",
                     "other": "other"}[name]
            extra = ""
            if s["code"]:
                extra = f", {s['code']:,} code lines ({_fmt_map(s['code_breakdown'])})"
            print(f"  [{label}]  {s['files']} files, {s['words']:,} words, "
                  f"{s['headings']:,} headings{extra}")

    # ----- global ------------------------------------------------------- #
    print(f"\n{'=' * W}")
    print("GLOBAL TOTALS (coursework)".center(W))
    print(f"{'=' * W}\n")

    print(f"  {'Courses:':<30} {sum(len(c) for c in stats.courses.values())}")
    print(f"  {'Files:':<30} {grand['files']:,}")
    print(f"  {'Prose words:':<30} {grand['words']:,}")
    print(f"  {'Code lines:':<30} {grand['code']:,}  ({grand['src_blocks']} src blocks)")
    if grand["code_langs"]:
        print(f"  {'  Breakdown:':<30} {_fmt_map(grand['code_langs'])}")
    print(f"  {'Math fragments:':<30} {grand['math']:,}"
          f"  (inline={grand['inline_math']:,}, display={grand['display_math']:,})")
    print(f"  {'Lines in math envs:':<30} {grand['math_lines']:,}")
    print(f"  {'Headings:':<30} {grand['headings']:,}")
    print(f"  {'Lectures / chapters:':<30} {grand['lectures']} / {grand['chapters']}")
    print(f"  {'Problem sets:':<30} {grand['problem_sets']}")
    if grand["extracted"]:
        pct = grand["extracted_with_prov"] / grand["extracted"] * 100
        print(f"  {'Extracted products:':<30} {grand['extracted']}"
              f"  (provenance {grand['extracted_with_prov']}/{grand['extracted']}, {pct:.0f}%)")
    print(f"  {'Prep day files:':<30} {grand['day_files']}")
    if grand["total_tasks"]:
        pct = grand["done"] / grand["total_tasks"] * 100
        print(f"  {'Tasks (done/total):':<30} {grand['done']}/{grand['total_tasks']} ({pct:.0f}%)")
    print(f"  {'Size (text, coursework):':<30} {grand['size_mb']:.2f} MB")
    print(f"\n{'=' * W}\n")


def _print_totals(acc, indent):
    pad = " " * indent
    print(f"{pad}{'Files:':<26} {acc['files']:>6,}")
    print(f"{pad}{'Words:':<26} {acc['words']:>6,}")
    print(f"{pad}{'Code lines:':<26} {acc['code']:>6,}  ({acc['src_blocks']} src blocks)")
    print(f"{pad}{'Math fragments:':<26} {acc['math']:>6,}"
          f"  (inline={acc['inline_math']:,}, display={acc['display_math']:,})")
    print(f"{pad}{'Headings:':<26} {acc['headings']:>6,}")
    if acc["extracted"]:
        pct = acc["extracted_with_prov"] / acc["extracted"] * 100
        print(f"{pad}{'Extracted (w/ prov):':<26} "
              f"{acc['extracted']} ({acc['extracted_with_prov']}, {pct:.0f}%)")
    if acc["total_tasks"]:
        pct = acc["done"] / acc["total_tasks"] * 100
        print(f"{pad}{'Tasks:':<26} {acc['done']}/{acc['total_tasks']} ({pct:.0f}%)")
    print(f"{pad}{'Size (text):':<26} {acc['size_mb']:>6.2f} MB")


# --------------------------------------------------------------------------- #
# file discovery
# --------------------------------------------------------------------------- #

def find_root(explicit: Path | None) -> Path:
    if explicit:
        root = explicit.resolve()
    else:
        # scripts/ -> 00_global/ -> repo   (same derivation as the validator)
        root = Path(__file__).resolve().parents[2]
    if not (root / "STRUCTURE.org").is_file():
        cwd = Path.cwd()
        if (cwd / "STRUCTURE.org").is_file():
            return cwd
        sys.exit(f"no STRUCTURE.org at {root} -- run from the repo or pass --root")
    return root


def list_files(root: Path, use_git: bool):
    if use_git:
        try:
            out = subprocess.run(
                ["git", "-C", str(root), "ls-files", "-z"],
                capture_output=True, text=True, check=True)
            names = [n for n in out.stdout.split("\0") if n]
            return [root / n for n in names]
        except (subprocess.CalledProcessError, FileNotFoundError):
            print("(git ls-files unavailable; walking the filesystem)",
                  file=sys.stderr)
    files = []
    for dp, dn, fn in os.walk(root):
        dn[:] = [d for d in dn if d not in IGNORE_DIRS and not d.startswith(".")]
        for f in fn:
            files.append(Path(dp) / f)
    return files


def main(argv=None):
    ap = argparse.ArgumentParser(description="repository analytics")
    ap.add_argument("--root", type=Path, default=None,
                    help="repo root (default: derived from this script's path)")
    ap.add_argument("--no-git", action="store_true",
                    help="walk the filesystem instead of using git ls-files")
    ap.add_argument("--top", type=int, default=10,
                    help="how many top tags / LaTeX commands to show")
    args = ap.parse_args(argv)

    root = find_root(args.root)
    stats = RepoStats(root)
    for path in list_files(root, use_git=not args.no_git):
        stats.analyze(path)
    report(stats, top=args.top)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
