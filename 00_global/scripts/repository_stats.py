import os
import re
from collections import defaultdict
from pathlib import Path

# --- CONFIGURATION ---
SKIP_DIRS = {'.git', '.obsidian', '__pycache__', 'chats', '_llm_logs'}
SKIP_EXTENSIONS = {'.pdf', '.png', '.jpg', '.jpeg', '.svg', '.gif', '.webp'}

LANG_MAP = {
    'jupyter-python': 'Python', 'python': 'Python',
    'julia': 'Julia',
    'bash': 'Shell', 'sh': 'Shell',
    'c++': 'C++', 'cpp': 'C++',
    'latex': 'LaTeX',
    'r': 'R',
    'emacs-lisp': 'Elisp', 'elisp': 'Elisp',
    'sql': 'SQL',
    'javascript': 'JavaScript', 'js': 'JavaScript',
    'typescript': 'TypeScript', 'ts': 'TypeScript',
    'html': 'HTML',
    'css': 'CSS',
    'rust': 'Rust',
    'haskell': 'Haskell',
    'ocaml': 'OCaml',
    'scheme': 'Scheme', 'racket': 'Racket',
    'gnuplot': 'Gnuplot',
    'dot': 'Graphviz',
}

# LaTeX environment names worth tracking individually
MATH_ENVS = {
    'equation', 'equation*', 'align', 'align*', 'gather', 'gather*',
    'multline', 'multline*', 'flalign', 'flalign*', 'eqnarray', 'eqnarray*',
    'split', 'cases', 'matrix', 'pmatrix', 'bmatrix', 'vmatrix', 'Vmatrix',
    'array',
}

THEOREM_ENVS = {
    'theorem', 'lemma', 'proposition', 'corollary', 'conjecture',
    'definition', 'example', 'examples', 'remark', 'remarks', 'note',
    'proof', 'exercise', 'problem', 'solution', 'claim',
}

# Regex patterns (compiled once)
RE_INLINE_MATH = re.compile(r'(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)')   # $...$
RE_DISPLAY_MATH_DOLLAR = re.compile(r'\$\$(.+?)\$\$', re.DOTALL)      # $$...$$
RE_DISPLAY_MATH_BRACKET = re.compile(r'\\\[')                          # \[
RE_INLINE_MATH_PAREN = re.compile(r'\\\(')                             # \(
RE_BEGIN_ENV = re.compile(r'\\begin\{(\w+\*?)\}')
RE_END_ENV = re.compile(r'\\end\{(\w+\*?)\}')
RE_ORG_HEADING = re.compile(r'^(\*+)\s')
RE_ORG_TAG = re.compile(r':([a-zA-Z0-9_@]+):$')
RE_ORG_LINK = re.compile(r'\[\[([^\]]+)\]')
RE_ORG_TIMESTAMP = re.compile(r'[<\[]\d{4}-\d{2}-\d{2}')
RE_ORG_FOOTNOTE = re.compile(r'\[fn:([^\]]+)\]')
RE_ORG_TABLE_ROW = re.compile(r'^\s*\|')
RE_ORG_PROPERTY = re.compile(r'^\s*:([A-Z_]+):\s')
RE_ORG_CITE = re.compile(r'\[cite[:/]')
RE_LATEX_CMD = re.compile(r'\\([a-zA-Z]+)')


# --- DATA STRUCTURES ---

def empty_course_stats():
    return {
        # File counts
        'org_files': 0, 'py_files': 0, 'jl_files': 0, 'other_files': 0,
        # Prose content
        'prose_lines': 0, 'prose_words': 0,
        # Code (lang -> lines, both standalone files and embedded src blocks)
        'code_lines': defaultdict(int),
        'src_blocks': defaultdict(int),      # lang -> number of #+begin_src blocks
        # LaTeX-in-org: granular math tracking
        'latex_inline_math': 0,              # $...$  count
        'latex_display_math': 0,             # $$...$$, \[...\], display envs
        'latex_math_envs': defaultdict(int), # env_name -> count  (equation, align, ...)
        'latex_theorem_envs': defaultdict(int),  # theorem, proof, definition, ...
        'latex_other_envs': defaultdict(int),    # figure, table, tikzpicture, ...
        'latex_math_lines': 0,               # total lines inside math environments
        'latex_commands': defaultdict(int),   # \cmd -> count (top-N reported)
        # Org structure
        'headings': defaultdict(int),        # depth -> count
        'tags': defaultdict(int),            # tag -> count
        'properties': defaultdict(int),      # property name -> count
        'org_links': 0,
        'org_timestamps': 0,
        'org_footnotes': 0,
        'org_tables_rows': 0,
        'org_citations': 0,
        'org_drawers': 0,
        # Tasks
        'todos': {'TODO': 0, 'DONE': 0, 'PROJ': 0},
        # Exercise sets
        'exercise_sets': set(),
        # Lecture files
        'lecture_files': 0,
        # Size
        'size_bytes': 0,
        # Deepest heading level encountered
        'max_heading_depth': 0,
    }


class RepoStats:
    def __init__(self, root_dir='.'):
        self.root = Path(root_dir).resolve()
        self.course_stats = defaultdict(lambda: defaultdict(empty_course_stats))
        self.global_stats = empty_course_stats()

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------

    def _classify_path(self, filepath):
        try:
            rel = Path(filepath).resolve().relative_to(self.root)
        except ValueError:
            return None, None
        parts = rel.parts
        if len(parts) >= 3 and parts[0] == '01_bachelor':
            return parts[1], parts[2]
        return None, None

    def _is_lecture_file(self, filepath):
        return '01_lectures' in str(filepath) or 'lecture_notes' in str(filepath)

    def _exercise_set(self, filepath):
        parts = Path(filepath).parts
        for i, p in enumerate(parts):
            if p == '02_exercises' and i + 1 < len(parts):
                return parts[i + 1]
        return None

    # ------------------------------------------------------------------
    # Core analysis
    # ------------------------------------------------------------------

    def analyze_file(self, filepath):
        path = Path(filepath)
        ext = path.suffix.lower()

        if ext in SKIP_EXTENSIONS:
            return

        try:
            size = path.stat().st_size
        except OSError:
            return

        semester, course = self._classify_path(filepath)
        target = self.course_stats[semester][course] if semester else self.global_stats
        target['size_bytes'] += size

        ex_set = self._exercise_set(filepath)
        if ex_set:
            target['exercise_sets'].add(ex_set)

        if self._is_lecture_file(filepath):
            target['lecture_files'] += 1

        try:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
        except Exception:
            return

        if ext == '.org':
            target['org_files'] += 1
            self._parse_org(lines, target)
        elif ext == '.py':
            target['py_files'] += 1
            target['code_lines']['Python'] += sum(1 for l in lines if l.strip() and not l.strip().startswith('#'))
        elif ext == '.jl':
            target['jl_files'] += 1
            target['code_lines']['Julia'] += sum(1 for l in lines if l.strip() and not l.strip().startswith('#'))
        else:
            target['other_files'] += 1

    # ------------------------------------------------------------------
    # Org parser — the heavy lifter
    # ------------------------------------------------------------------

    def _parse_org(self, lines, target):
        in_src_block = False
        current_lang = None
        in_latex_env = False          # inside \begin{...} ... \end{...}
        current_env = None
        in_drawer = False

        for line in lines:
            stripped = line.strip()

            # ---- Drawers (:PROPERTIES:, :LOGBOOK:, etc.) ----
            if stripped.startswith(':') and stripped.endswith(':') and len(stripped) > 2:
                upper = stripped[1:-1]
                if upper == 'END':
                    in_drawer = False
                    continue
                elif upper.isupper() and '_' not in upper.strip('_'):
                    in_drawer = True
                    target['org_drawers'] += 1
                    continue

            if in_drawer:
                # Track properties inside :PROPERTIES: drawer
                m = RE_ORG_PROPERTY.match(line)
                if m:
                    target['properties'][m.group(1)] += 1
                continue

            # ---- Source blocks ----
            if stripped.lower().startswith('#+begin_src'):
                in_src_block = True
                parts = stripped.split()
                raw_lang = parts[1].lower() if len(parts) > 1 else 'unknown'
                current_lang = LANG_MAP.get(raw_lang, raw_lang)
                target['src_blocks'][current_lang] += 1
                continue

            if stripped.lower().startswith('#+end_src'):
                in_src_block = False
                current_lang = None
                continue

            if in_src_block:
                if stripped and not stripped.startswith('#'):
                    target['code_lines'][current_lang] += 1
                continue

            # ---- Skip other org special blocks (#+begin_quote, etc.) ----
            # (still count their content as prose below)

            # ---- LaTeX environments (\begin{...} / \end{...}) ----
            begin_m = RE_BEGIN_ENV.search(line)
            end_m = RE_END_ENV.search(line)

            if begin_m and not in_latex_env:
                env_name = begin_m.group(1)
                in_latex_env = True
                current_env = env_name
                if env_name in MATH_ENVS:
                    target['latex_math_envs'][env_name] += 1
                    target['latex_display_math'] += 1
                elif env_name in THEOREM_ENVS:
                    target['latex_theorem_envs'][env_name] += 1
                else:
                    target['latex_other_envs'][env_name] += 1

            if in_latex_env:
                if current_env in MATH_ENVS:
                    target['latex_math_lines'] += 1

            if end_m and in_latex_env and end_m.group(1) == current_env:
                in_latex_env = False
                current_env = None

            # ---- Inline and display math (not inside environments) ----
            if not in_latex_env:
                target['latex_inline_math'] += len(RE_INLINE_MATH.findall(line))
                target['latex_display_math'] += len(RE_DISPLAY_MATH_DOLLAR.findall(line))
                target['latex_display_math'] += len(RE_DISPLAY_MATH_BRACKET.findall(line))
                # \( counts as inline
                target['latex_inline_math'] += len(RE_INLINE_MATH_PAREN.findall(line))

            # ---- LaTeX commands ----
            for cmd in RE_LATEX_CMD.findall(line):
                target['latex_commands'][cmd] += 1

            # ---- Org headings ----
            hm = RE_ORG_HEADING.match(line)
            if hm:
                depth = len(hm.group(1))
                target['headings'][depth] += 1
                if depth > target['max_heading_depth']:
                    target['max_heading_depth'] = depth

                # Tags on heading line
                tag_part = line.rstrip()
                tm = RE_ORG_TAG.search(tag_part)
                if tm:
                    tag_str = tag_part[tag_part.rfind(':'):]
                    # parse :tag1:tag2:
                    raw = tag_part.split()[-1] if ':' in tag_part.split()[-1] else ''
                    for t in raw.strip(':').split(':'):
                        if t:
                            target['tags'][t] += 1

                # TODOs
                for kw in ('TODO', 'DONE', 'PROJ'):
                    if f' {kw} ' in line or line.rstrip().endswith(f' {kw}'):
                        target['todos'][kw] += 1

            # ---- Links, timestamps, footnotes, citations ----
            target['org_links'] += len(RE_ORG_LINK.findall(line))
            target['org_timestamps'] += len(RE_ORG_TIMESTAMP.findall(line))
            target['org_footnotes'] += len(RE_ORG_FOOTNOTE.findall(line))
            target['org_citations'] += len(RE_ORG_CITE.findall(line))

            # ---- Tables ----
            if RE_ORG_TABLE_ROW.match(line):
                target['org_tables_rows'] += 1

            # ---- Prose ----
            if stripped and not stripped.startswith('#') and not stripped.startswith('|'):
                target['prose_lines'] += 1
                target['prose_words'] += len(line.split())

    # ------------------------------------------------------------------
    # Aggregation
    # ------------------------------------------------------------------

    def _sum_course(self, cs):
        total_files = cs['org_files'] + cs['py_files'] + cs['jl_files'] + cs['other_files']
        total_code = sum(cs['code_lines'].values())
        total_src_blocks = sum(cs['src_blocks'].values())
        total_math_frags = cs['latex_inline_math'] + cs['latex_display_math']
        total_math_envs = sum(cs['latex_math_envs'].values())
        total_theorem_envs = sum(cs['latex_theorem_envs'].values())
        total_other_envs = sum(cs['latex_other_envs'].values())
        tasks_done = cs['todos']['DONE']
        tasks_total = cs['todos']['TODO'] + cs['todos']['DONE']
        total_headings = sum(cs['headings'].values())
        return {
            'words': cs['prose_words'],
            'prose_lines': cs['prose_lines'],
            'files': total_files,
            'code_lines': total_code,
            'src_blocks': total_src_blocks,
            'code_breakdown': dict(cs['code_lines']),
            'src_block_breakdown': dict(cs['src_blocks']),
            # LaTeX
            'inline_math': cs['latex_inline_math'],
            'display_math': cs['latex_display_math'],
            'total_math_frags': total_math_frags,
            'math_envs': total_math_envs,
            'math_env_breakdown': dict(cs['latex_math_envs']),
            'theorem_envs': total_theorem_envs,
            'theorem_env_breakdown': dict(cs['latex_theorem_envs']),
            'other_envs': total_other_envs,
            'other_env_breakdown': dict(cs['latex_other_envs']),
            'math_lines': cs['latex_math_lines'],
            # Org structure
            'headings': total_headings,
            'heading_depth': dict(cs['headings']),
            'max_depth': cs['max_heading_depth'],
            'tags': dict(cs['tags']),
            'links': cs['org_links'],
            'timestamps': cs['org_timestamps'],
            'footnotes': cs['org_footnotes'],
            'citations': cs['org_citations'],
            'table_rows': cs['org_tables_rows'],
            'drawers': cs['org_drawers'],
            # Tasks
            'tasks_done': tasks_done,
            'tasks_total': tasks_total,
            'ex_sets': len(cs['exercise_sets']),
            'lecture_files': cs['lecture_files'],
            'size_mb': cs['size_bytes'] / (1024 * 1024),
            # Top LaTeX commands
            'top_cmds': dict(sorted(cs['latex_commands'].items(),
                                    key=lambda x: -x[1])[:15]),
        }

    # ------------------------------------------------------------------
    # Report
    # ------------------------------------------------------------------

    def print_report(self):
        W = 78
        print()
        print("=" * W)
        print("STUDY REPOSITORY ANALYTICS".center(W))
        print("=" * W)

        for semester in sorted(self.course_stats.keys()):
            courses = self.course_stats[semester]
            print(f"\n{'─'*W}")
            print(f"  SEMESTER: {semester}")
            print(f"{'─'*W}")

            sem = defaultdict(int, {'size_mb': 0.0})

            for course in sorted(courses.keys()):
                cs = courses[course]
                s = self._sum_course(cs)

                print(f"\n  [{course}]")
                print(f"    {'Files:':<28} {s['files']:>6}  "
                      f"(org={cs['org_files']}, py={cs['py_files']}, jl={cs['jl_files']}, other={cs['other_files']})")
                print(f"    {'Prose:':<28} {s['words']:>6,} words  /  {s['prose_lines']:,} lines")

                # -- LaTeX detail --
                print(f"    {'LaTeX (inline $...$):':<28} {s['inline_math']:>6,}")
                print(f"    {'LaTeX (display):':<28} {s['display_math']:>6,}")
                if s['math_env_breakdown']:
                    envs = ', '.join(f"{e}={c}" for e, c in sorted(s['math_env_breakdown'].items(), key=lambda x: -x[1]))
                    print(f"    {'  Math environments:':<28} {envs}")
                if s['theorem_env_breakdown']:
                    envs = ', '.join(f"{e}={c}" for e, c in sorted(s['theorem_env_breakdown'].items(), key=lambda x: -x[1]))
                    print(f"    {'  Theorem-like envs:':<28} {envs}")
                if s['other_env_breakdown']:
                    envs = ', '.join(f"{e}={c}" for e, c in sorted(s['other_env_breakdown'].items(), key=lambda x: -x[1])[:10])
                    print(f"    {'  Other LaTeX envs:':<28} {envs}")
                print(f"    {'  Math env lines:':<28} {s['math_lines']:>6,}")

                # -- Code --
                print(f"    {'Code lines:':<28} {s['code_lines']:>6,}  ({s['src_blocks']} blocks)")
                if s['code_breakdown']:
                    bd = ', '.join(f"{l}={c}" for l, c in sorted(s['code_breakdown'].items(), key=lambda x: -x[1]))
                    print(f"    {'  Breakdown:':<28} {bd}")

                # -- Org structure --
                print(f"    {'Headings:':<28} {s['headings']:>6,}  (max depth={s['max_depth']})")
                if s['heading_depth']:
                    hd = ', '.join(f"L{d}={c}" for d, c in sorted(s['heading_depth'].items()))
                    print(f"    {'  By depth:':<28} {hd}")
                print(f"    {'Links:':<28} {s['links']:>6,}")
                print(f"    {'Timestamps:':<28} {s['timestamps']:>6,}")
                print(f"    {'Table rows:':<28} {s['table_rows']:>6,}")
                if s['footnotes']:
                    print(f"    {'Footnotes:':<28} {s['footnotes']:>6,}")
                if s['citations']:
                    print(f"    {'Citations:':<28} {s['citations']:>6,}")
                if s['drawers']:
                    print(f"    {'Drawers:':<28} {s['drawers']:>6,}")

                # -- Tags --
                if s['tags']:
                    top_tags = sorted(s['tags'].items(), key=lambda x: -x[1])[:10]
                    tstr = ', '.join(f":{t}:={c}" for t, c in top_tags)
                    print(f"    {'Top tags:':<28} {tstr}")

                # -- Tasks --
                if s['tasks_total'] > 0:
                    pct = s['tasks_done'] / s['tasks_total'] * 100
                    print(f"    {'Tasks (done/total):':<28} {s['tasks_done']}/{s['tasks_total']} ({pct:.0f}%)")
                print(f"    {'Exercise sets:':<28} {s['ex_sets']:>6}")
                print(f"    {'Lecture files:':<28} {s['lecture_files']:>6}")
                print(f"    {'Size:':<28} {s['size_mb']:>6.2f} MB")

                # -- Top LaTeX commands --
                if s['top_cmds']:
                    cmds = ', '.join(f"\\{c}={n}" for c, n in list(s['top_cmds'].items())[:10])
                    print(f"    {'Top LaTeX cmds:':<28} {cmds}")

                # accumulate semester totals
                for k in ('words', 'code_lines', 'src_blocks', 'inline_math', 'display_math',
                          'math_envs', 'theorem_envs', 'math_lines', 'headings', 'links',
                          'timestamps', 'table_rows', 'footnotes', 'citations', 'drawers',
                          'tasks_done', 'tasks_total', 'files', 'ex_sets', 'lecture_files'):
                    sem[k] += s[k]
                sem['size_mb'] += s['size_mb']

            # Semester summary
            print(f"\n  {'Semester totals':─<{W-2}}")
            print(f"    {'Files:':<28} {sem['files']:>6,}")
            print(f"    {'Words:':<28} {sem['words']:>6,}")
            print(f"    {'Code lines:':<28} {sem['code_lines']:>6,}  ({sem['src_blocks']} blocks)")
            print(f"    {'Math (inline+display):':<28} {sem['inline_math'] + sem['display_math']:>6,}"
                  f"  (inline={sem['inline_math']:,}, display={sem['display_math']:,})")
            print(f"    {'Math env lines:':<28} {sem['math_lines']:>6,}")
            print(f"    {'Headings:':<28} {sem['headings']:>6,}")
            print(f"    {'Links:':<28} {sem['links']:>6,}")
            if sem['tasks_total'] > 0:
                pct = sem['tasks_done'] / sem['tasks_total'] * 100
                print(f"    {'Tasks:':<28} {sem['tasks_done']}/{sem['tasks_total']} ({pct:.0f}%)")
            print(f"    {'Size:':<28} {sem['size_mb']:>6.2f} MB")

        # ---- Global summary ----
        print(f"\n{'='*W}")
        print("GLOBAL TOTALS".center(W))
        print(f"{'='*W}")

        g = defaultdict(int, {'size_mb': 0.0, 'code_langs': defaultdict(int)})

        for _, courses in self.course_stats.items():
            for _, cs in courses.items():
                s = self._sum_course(cs)
                g['words'] += s['words']
                g['code_lines'] += s['code_lines']
                g['src_blocks'] += s['src_blocks']
                g['inline_math'] += s['inline_math']
                g['display_math'] += s['display_math']
                g['math_envs'] += s['math_envs']
                g['theorem_envs'] += s['theorem_envs']
                g['math_lines'] += s['math_lines']
                g['headings'] += s['headings']
                g['links'] += s['links']
                g['timestamps'] += s['timestamps']
                g['table_rows'] += s['table_rows']
                g['footnotes'] += s['footnotes']
                g['citations'] += s['citations']
                g['drawers'] += s['drawers']
                g['tasks_done'] += s['tasks_done']
                g['tasks_total'] += s['tasks_total']
                g['files'] += s['files']
                g['size_mb'] += s['size_mb']
                for lang, cnt in s['code_breakdown'].items():
                    g['code_langs'][lang] += cnt

        # Add non-course global stats
        gs = self._sum_course(self.global_stats)
        g['words'] += gs['words']
        g['code_lines'] += gs['code_lines']
        g['src_blocks'] += gs['src_blocks']
        g['inline_math'] += gs['inline_math']
        g['display_math'] += gs['display_math']
        g['math_envs'] += gs['math_envs']
        g['theorem_envs'] += gs['theorem_envs']
        g['math_lines'] += gs['math_lines']
        g['headings'] += gs['headings']
        g['links'] += gs['links']
        g['timestamps'] += gs['timestamps']
        g['table_rows'] += gs['table_rows']
        g['footnotes'] += gs['footnotes']
        g['citations'] += gs['citations']
        g['drawers'] += gs['drawers']
        g['tasks_done'] += gs['tasks_done']
        g['tasks_total'] += gs['tasks_total']
        g['files'] += gs['files']
        g['size_mb'] += gs['size_mb']
        for lang, cnt in gs['code_breakdown'].items():
            g['code_langs'][lang] += cnt

        total_math = g['inline_math'] + g['display_math']

        print(f"\n  {'Total files:':<32} {g['files']:,}")
        print(f"  {'Total prose words:':<32} {g['words']:,}")
        print(f"  {'Total code lines:':<32} {g['code_lines']:,}  ({g['src_blocks']} blocks)")
        if g['code_langs']:
            print(f"  {'  Code breakdown:':<32} ",
                  end='')
            print(', '.join(f"{l}={c:,}" for l, c in sorted(g['code_langs'].items(), key=lambda x: -x[1])))
        print(f"  {'Total math fragments:':<32} {total_math:,}"
              f"  (inline={g['inline_math']:,}, display={g['display_math']:,})")
        print(f"  {'  Math env instances:':<32} {g['math_envs']:,}")
        print(f"  {'  Theorem-like env instances:':<32} {g['theorem_envs']:,}")
        print(f"  {'  Lines inside math envs:':<32} {g['math_lines']:,}")
        print(f"  {'Total headings:':<32} {g['headings']:,}")
        print(f"  {'Total links:':<32} {g['links']:,}")
        print(f"  {'Total timestamps:':<32} {g['timestamps']:,}")
        print(f"  {'Total table rows:':<32} {g['table_rows']:,}")
        if g['footnotes']:
            print(f"  {'Total footnotes:':<32} {g['footnotes']:,}")
        if g['citations']:
            print(f"  {'Total citations:':<32} {g['citations']:,}")
        if g['tasks_total'] > 0:
            pct = g['tasks_done'] / g['tasks_total'] * 100
            print(f"  {'Tasks (done/total):':<32} {g['tasks_done']}/{g['tasks_total']} ({pct:.0f}%)")
        print(f"  {'Repo size (text files):':<32} {g['size_mb']:.2f} MB")
        print(f"\n{'='*W}\n")

    def generate_org_table(self):
        """Org-mode table for README.org"""
        g_words = g_code = g_math = g_done = g_headings = g_thm = 0

        for _, courses in self.course_stats.items():
            for _, cs in courses.items():
                s = self._sum_course(cs)
                g_words += s['words']
                g_code += s['code_lines']
                g_math += s['inline_math'] + s['display_math']
                g_done += s['tasks_done']
                g_headings += s['headings']
                g_thm += s['theorem_envs']

        print("\n* Copy-Paste into README.org:\n")
        print("| Metric | Count | Description |")
        print("|---|---|---|")
        print(f"| *Knowledge Base* | {g_words:,} words | Prose notes (org-mode) |")
        print(f"| *Code Logic* | {g_code:,} lines | Python, Julia, Shell, C++ (embedded + source) |")
        print(f"| *Math Intensity* | {g_math:,} fragments | Inline ($) + display ($$, environments) |")
        print(f"| *Formal Structures* | {g_thm:,} environments | Theorems, proofs, definitions, lemmas |")
        print(f"| *Study Progress* | {g_done} tasks | Completed DONE headings |")
        print(f"| *Org Headings* | {g_headings:,} | Structural outline depth |")


def main():
    root_dir = "../../"
    analyzer = RepoStats(root_dir)

    for root, dirs, files in os.walk(root_dir):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith('.')]
        for file in files:
            analyzer.analyze_file(os.path.join(root, file))

    analyzer.print_report()
    analyzer.generate_org_table()


if __name__ == "__main__":
    main()
