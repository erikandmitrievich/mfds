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
}

# --- DATA STRUCTURES ---

def empty_course_stats():
    return {
        # File counts
        'org_files': 0, 'tex_files': 0, 'py_files': 0, 'jl_files': 0, 'other_files': 0,
        # Content
        'prose_lines': 0, 'prose_words': 0,
        'tex_lines': 0, 'tex_words': 0,
        'code_lines': defaultdict(int),   # lang -> lines (both .jl/.py and embedded in org)
        # Math
        'math_expressions': 0,
        # Tasks
        'todos': {'TODO': 0, 'DONE': 0, 'PROJ': 0},
        # Exercise sets
        'exercise_sets': set(),
        # Lecture files
        'lecture_files': 0,
        # Size
        'size_bytes': 0,
    }


class RepoStats:
    def __init__(self, root_dir='.'):
        self.root = Path(root_dir).resolve()
        # course_stats: {semester: {course: stats_dict}}
        self.course_stats = defaultdict(lambda: defaultdict(empty_course_stats))
        # global totals (everything outside semester/course structure too)
        self.global_stats = empty_course_stats()

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------

    def _classify_path(self, filepath):
        """
        Returns (semester, course) strings if inside 01_bachelor structure,
        otherwise (None, None).
        """
        try:
            rel = Path(filepath).resolve().relative_to(self.root)
        except ValueError:
            return None, None

        parts = rel.parts
        # Expected: 01_bachelor / {semester} / {course} / ...
        if len(parts) >= 3 and parts[0] == '01_bachelor':
            return parts[1], parts[2]
        return None, None

    def _is_lecture_file(self, filepath):
        return '01_lectures' in str(filepath) or 'lecture_notes' in str(filepath)

    def _exercise_set(self, filepath):
        """Return the exercise set name if inside an exercise set, else None."""
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

        # Track exercise set membership
        ex_set = self._exercise_set(filepath)
        if ex_set:
            target['exercise_sets'].add(ex_set)

        # Track lecture files
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
        elif ext == '.tex':
            target['tex_files'] += 1
            self._parse_tex(lines, target)
        elif ext == '.py':
            target['py_files'] += 1
            target['code_lines']['Python'] += sum(1 for l in lines if l.strip() and not l.strip().startswith('#'))
        elif ext == '.jl':
            target['jl_files'] += 1
            target['code_lines']['Julia'] += sum(1 for l in lines if l.strip() and not l.strip().startswith('#'))
        else:
            target['other_files'] += 1

    def _parse_org(self, lines, target):
        in_src_block = False
        current_lang = None

        for line in lines:
            stripped = line.strip()

            if stripped.lower().startswith('#+begin_src'):
                in_src_block = True
                parts = stripped.split()
                current_lang = LANG_MAP.get(parts[1].lower(), parts[1].lower()) if len(parts) > 1 else 'unknown'
                continue

            if stripped.lower().startswith('#+end_src'):
                in_src_block = False
                current_lang = None
                continue

            if in_src_block:
                if stripped and not stripped.startswith('#'):
                    target['code_lines'][current_lang] += 1
            else:
                # Prose
                if stripped:
                    target['prose_lines'] += 1
                    target['prose_words'] += len(line.split())

                # Math expressions (lines containing LaTeX math markers)
                if '$' in line or '\\[' in line or '\\(' in line or '\\begin{' in line:
                    target['math_expressions'] += 1

                # TODOs
                if stripped.startswith('*'):
                    for kw in ('TODO', 'DONE', 'PROJ'):
                        if f' {kw} ' in line or line.rstrip().endswith(f' {kw}'):
                            target['todos'][kw] += 1

    def _parse_tex(self, lines, target):
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith('%'):
                continue
            target['tex_lines'] += 1
            target['tex_words'] += len(stripped.split())
            if '$' in line or '\\[' in line or '\\(' in line or '\\begin{' in line:
                target['math_expressions'] += 1

    # ------------------------------------------------------------------
    # Aggregation helpers
    # ------------------------------------------------------------------

    def _sum_course(self, cs):
        """Flatten a course-stats dict into aggregate scalars."""
        total_words = cs['prose_words'] + cs['tex_words']
        total_lines = cs['prose_lines'] + cs['tex_lines'] + sum(cs['code_lines'].values())
        total_files = cs['org_files'] + cs['tex_files'] + cs['py_files'] + cs['jl_files'] + cs['other_files']
        total_code = sum(cs['code_lines'].values())
        tasks_done = cs['todos']['DONE']
        tasks_total = cs['todos']['TODO'] + cs['todos']['DONE']
        return {
            'words': total_words,
            'lines': total_lines,
            'files': total_files,
            'code_lines': total_code,
            'prose_words': cs['prose_words'],
            'tex_words': cs['tex_words'],
            'math': cs['math_expressions'],
            'tasks_done': tasks_done,
            'tasks_total': tasks_total,
            'ex_sets': len(cs['exercise_sets']),
            'lecture_files': cs['lecture_files'],
            'size_mb': cs['size_bytes'] / (1024 * 1024),
            'code_breakdown': dict(cs['code_lines']),
        }

    # ------------------------------------------------------------------
    # Report
    # ------------------------------------------------------------------

    def print_report(self):
        W = 72
        print()
        print("=" * W)
        print(f"  STUDY REPOSITORY ANALYTICS".center(W))
        print("=" * W)

        # ---- Per-Semester / Per-Course breakdown ----
        for semester in sorted(self.course_stats.keys()):
            courses = self.course_stats[semester]
            print(f"\n{'─'*W}")
            print(f"  SEMESTER: {semester}")
            print(f"{'─'*W}")

            sem_totals = {'words': 0, 'prose_words': 0, 'tex_words': 0,
                          'code_lines': 0, 'math': 0, 'tasks_done': 0,
                          'tasks_total': 0, 'files': 0, 'ex_sets': 0,
                          'lecture_files': 0, 'size_mb': 0.0}

            for course in sorted(courses.keys()):
                cs = courses[course]
                s = self._sum_course(cs)

                print(f"\n  [{course}]")
                print(f"    {'Files:':<26} {s['files']:>6}  (org={cs['org_files']}, tex={cs['tex_files']}, py={cs['py_files']}, jl={cs['jl_files']})")
                print(f"    {'Total words:':<26} {s['words']:>6,}  (prose={cs['prose_words']:,}, latex={cs['tex_words']:,})")
                print(f"    {'Total content lines:':<26} {s['lines']:>6,}  (prose={cs['prose_lines']:,}, code={s['code_lines']:,})")
                print(f"    {'Math expressions:':<26} {s['math']:>6,}")
                if s['code_breakdown']:
                    breakdown = ', '.join(f"{lang}={cnt}" for lang, cnt in sorted(s['code_breakdown'].items()))
                    print(f"    {'Code breakdown:':<26} {breakdown}")
                if s['tasks_total'] > 0:
                    pct = s['tasks_done'] / s['tasks_total'] * 100
                    print(f"    {'Tasks (done/total):':<26} {s['tasks_done']}/{s['tasks_total']} ({pct:.0f}%)")
                print(f"    {'Exercise sets:':<26} {s['ex_sets']:>6}")
                print(f"    {'Lecture files:':<26} {s['lecture_files']:>6}")
                print(f"    {'Size:':<26} {s['size_mb']:>6.2f} MB")

                for k in ('words', 'prose_words', 'tex_words', 'code_lines', 'math',
                          'tasks_done', 'tasks_total', 'files', 'ex_sets',
                          'lecture_files'):
                    sem_totals[k] += s[k]
                sem_totals['size_mb'] += s['size_mb']

            # Semester summary
            print(f"\n  {'Semester totals':─<{W-2}}")
            print(f"    {'Files:':<26} {sem_totals['files']:>6,}")
            print(f"    {'Total words:':<26} {sem_totals['words']:>6,}  (prose={sem_totals['prose_words']:,}, latex={sem_totals['tex_words']:,})")
            print(f"    {'Code lines:':<26} {sem_totals['code_lines']:>6,}")
            print(f"    {'Math expressions:':<26} {sem_totals['math']:>6,}")
            print(f"    {'Exercise sets:':<26} {sem_totals['ex_sets']:>6}")
            print(f"    {'Lecture files:':<26} {sem_totals['lecture_files']:>6}")
            print(f"    {'Size:':<26} {sem_totals['size_mb']:>6.2f} MB")

        # ---- Global summary ----
        print(f"\n{'='*W}")
        print(f"  GLOBAL TOTALS".center(W))
        print(f"{'='*W}")

        grand = {'words': 0, 'prose_words': 0, 'tex_words': 0,
                 'code_lines': defaultdict(int), 'math': 0,
                 'tasks_done': 0, 'tasks_total': 0, 'files': 0, 'size_mb': 0.0}

        for semester, courses in self.course_stats.items():
            for course, cs in courses.items():
                s = self._sum_course(cs)
                grand['words'] += s['words']
                grand['prose_words'] += s['prose_words']
                grand['tex_words'] += s['tex_words']
                grand['math'] += s['math']
                grand['tasks_done'] += s['tasks_done']
                grand['tasks_total'] += s['tasks_total']
                grand['files'] += s['files']
                grand['size_mb'] += s['size_mb']
                for lang, cnt in s['code_breakdown'].items():
                    grand['code_lines'][lang] += cnt

        # include global (non-course) stats
        gs = self._sum_course(self.global_stats)
        grand['words'] += gs['words']
        grand['prose_words'] += gs['prose_words']
        grand['tex_words'] += gs['tex_words']
        grand['math'] += gs['math']
        grand['tasks_done'] += gs['tasks_done']
        grand['tasks_total'] += gs['tasks_total']
        grand['files'] += gs['files']
        grand['size_mb'] += gs['size_mb']
        for lang, cnt in gs['code_breakdown'].items():
            grand['code_lines'][lang] += cnt

        total_code = sum(grand['code_lines'].values())
        print(f"\n  {'Total files:':<30} {grand['files']:,}")
        print(f"  {'Total words:':<30} {grand['words']:,}  (prose={grand['prose_words']:,}, latex={grand['tex_words']:,})")
        print(f"  {'Total code lines:':<30} {total_code:,}")
        if grand['code_lines']:
            print(f"  {'  Code breakdown:':<30} ", end='')
            print(', '.join(f"{lang}={cnt:,}" for lang, cnt in sorted(grand['code_lines'].items())))
        print(f"  {'Total math expressions:':<30} {grand['math']:,}")
        if grand['tasks_total'] > 0:
            pct = grand['tasks_done'] / grand['tasks_total'] * 100
            print(f"  {'Tasks (done/total):':<30} {grand['tasks_done']}/{grand['tasks_total']} ({pct:.0f}%)")
        print(f"  {'Repo size (text files):':<30} {grand['size_mb']:.2f} MB")
        print(f"\n{'='*W}\n")

    def generate_org_table(self):
        """Generates an Org-mode table for README.org"""
        grand_words = 0
        grand_code = 0
        grand_math = 0
        grand_done = 0

        for semester, courses in self.course_stats.items():
            for course, cs in courses.items():
                s = self._sum_course(cs)
                grand_words += s['words']
                grand_code += s['code_lines']
                grand_math += s['math']
                grand_done += s['tasks_done']

        print("\n* Copy-Paste into README.org:\n")
        print("| Metric | Count | Description |")
        print("|---|---|---|")
        print(f"| *Knowledge Base* | {grand_words:,} words | Prose notes + LaTeX files |")
        print(f"| *Code Logic* | {grand_code:,} lines | Python, Julia, Shell, C++ (embedded + source) |")
        print(f"| *Math Intensity* | {grand_math:,} lines | Lines containing LaTeX math |")
        print(f"| *Study Progress* | {grand_done} tasks | Completed DONE headings |")


def main():
    root_dir = "."
    analyzer = RepoStats(root_dir)

    for root, dirs, files in os.walk(root_dir):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith('.')]
        for file in files:
            analyzer.analyze_file(os.path.join(root, file))

    analyzer.print_report()
    analyzer.generate_org_table()


if __name__ == "__main__":
    main()
