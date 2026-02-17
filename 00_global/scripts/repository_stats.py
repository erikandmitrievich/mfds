import os
import re
from collections import defaultdict
from pathlib import Path

# --- CONFIGURATION ---
SKIP_DIRS = {'.git', '.obsidian', 'pdfs', '__pycache__'}
SKIP_EXTENSIONS = {'.pdf', '.png', '.jpg', '.jpeg', '.svg', '.gif'}

class RepoStats:
    def __init__(self):
        self.stats = defaultdict(lambda: {'files': 0, 'lines': 0, 'words': 0})
        self.org_code_stats = defaultdict(lambda: {'lines': 0}) 
        self.math_equations = 0
        self.todos = {'TODO': 0, 'DONE': 0, 'PROJ': 0}
        self.total_size_mb = 0

    def analyze_file(self, filepath):
        path = Path(filepath)
        ext = path.suffix.lower()
        
        if ext in SKIP_EXTENSIONS:
            return

        try:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
        except Exception as e:
            print(f"Skipping {filepath}: {e}")
            return

        # Basic File Stats
        line_count = len(lines)
        word_count = sum(len(line.split()) for line in lines)
        self.total_size_mb += path.stat().st_size / (1024 * 1024)

        # Categorize by extension
        if ext == '.org':
            self.stats['Org-Mode (Prose)']['files'] += 1
            self._parse_org_deep(lines)
        elif ext == '.jl':
            self.stats['Julia']['files'] += 1
            self.stats['Julia']['lines'] += line_count
        elif ext == '.py':
            self.stats['Python']['files'] += 1
            self.stats['Python']['lines'] += line_count
        elif ext == '.tex':
            self.stats['LaTeX']['files'] += 1
            self.stats['LaTeX']['lines'] += line_count
        else:
            # Catch-all for other text files
            pass

    def _parse_org_deep(self, lines):
        """
        Parses Org lines to separate Prose, Embedded Code, and Math.
        """
        in_src_block = False
        current_lang = None
        prose_lines = 0
        prose_words = 0

        for line in lines:
            stripped = line.strip()

            # 1. Detect Code Blocks
            if stripped.lower().startswith('#+begin_src'):
                in_src_block = True
                # Extract language (e.g., "#+begin_src python" -> "python")
                parts = stripped.split()
                if len(parts) > 1:
                    current_lang = parts[1].lower()
                else:
                    current_lang = 'unknown'
                continue # Don't count the marker line as code

            if stripped.lower().startswith('#+end_src'):
                in_src_block = False
                current_lang = None
                continue

            # 2. Count Logic
            if in_src_block:
                # Map org languages to pretty names
                lang_map = {'jupyter-python': 'Python', 'python': 'Python', 'julia': 'Julia', 'bash': 'Shell', 'sh': 'Shell', 'c++': 'C++', 'cpp': 'C++'}
                nice_lang = lang_map.get(current_lang, f"Embedded {current_lang}")
                self.org_code_stats[nice_lang]['lines'] += 1
            else:
                # It is prose/notes
                prose_lines += 1
                prose_words += len(line.split())

                # 3. Detect Math (Simple Heuristic)
                # inline $...$ or display \[...\] or \begin{equation}
                if '$' in line or '\\[' in line or '\\begin' in line:
                    self.math_equations += 1
                
                # 4. Detect TODOs
                if stripped.startswith('*'):
                    if ' TODO ' in line: self.todos['TODO'] += 1
                    if ' DONE ' in line: self.todos['DONE'] += 1
                    if ' PROJ ' in line: self.todos['PROJ'] += 1

        self.stats['Org-Mode (Prose)']['lines'] += prose_lines
        self.stats['Org-Mode (Prose)']['words'] += prose_words

    def print_report(self):
        print("\n" + "="*50)
        print(f" STUDY REPO ANALYTICS")
        print("="*50)
        
        # 1. Code Breakdown
        print(f"\n[CODE VOLUME]")
        print(f"{'Language':<20} | {'Files':<5} | {'Lines':<8} | {'Source'}")
        print("-" * 50)
        
        # Merge pure files and embedded code
        combined_stats = {}
        
        # Add pure files
        for lang, data in self.stats.items():
            if lang == 'Org-Mode (Prose)': continue
            combined_stats[lang] = data['lines']
            print(f"{lang:<20} | {data['files']:<5} | {data['lines']:<8} | .{''.join([c for c in lang if c.islower()])} files")

        # Add embedded
        for lang, data in self.org_code_stats.items():
            if data['lines'] > 0:
                print(f"{lang:<20} | {'-':<5} | {data['lines']:<8} | Inside .org")

        print("-" * 50)

        # 2. Knowledge Base
        org = self.stats['Org-Mode (Prose)']
        print(f"\n[KNOWLEDGE BASE]")
        print(f"Total Notes (Org):    {org['lines']:,} lines ({org['words']:,} words)")
        print(f"Math Expressions:     {self.math_equations:,} (approx. detected)")
        print(f"Tasks Completed:      {self.todos['DONE']} / {self.todos['TODO'] + self.todos['DONE']} ({(self.todos['DONE'] / (self.todos['DONE'] + self.todos['TODO'] + 1))*100:.1f}%)")

        print(f"\nTotal Repo Size:      {self.total_size_mb:.2f} MB")
        print("="*50 + "\n")

    def generate_org_table(self):
        """Generates a text block you can copy-paste into README.org"""
        org = self.stats['Org-Mode (Prose)']
        
        # Calculate totals
        total_code_lines = sum(d['lines'] for k, d in self.stats.items() if k != 'Org-Mode (Prose)') + \
                           sum(d['lines'] for d in self.org_code_stats.values())

        print("* Copy-Paste this into your README:\n")
        print("| Metric | Count | Description |")
        print("|---|---|---|")
        print(f"| **Knowledge Base** | {org['words']:,} words | Across {org['files']} Org files |")
        print(f"| **Code Logic** | {total_code_lines:,} lines | Python, Julia, C++ (including embedded) |")
        print(f"| **Math Intensity** | {self.math_equations:,} eq | LaTeX expressions detected |")
        print(f"| **Study Progress** | {self.todos['DONE']} tasks | Completed units/exams |")

def main():
    analyzer = RepoStats()
    root_dir = "."  # Current directory

    for root, dirs, files in os.walk(root_dir):
        # Filter directories
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith('.')]
        
        for file in files:
            analyzer.analyze_file(os.path.join(root, file))

    analyzer.print_report()
    analyzer.generate_org_table()

if __name__ == "__main__":
    main()
