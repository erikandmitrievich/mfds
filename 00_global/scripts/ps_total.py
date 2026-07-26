#!/usr/bin/env python3

import re
import sys
from pathlib import Path
import argparse

def extract_problems(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    # Regex patterns
    # Matches top-level problem headings (e.g., "* Problem 1", "* Problem 1 :DONE:")
    problem_pattern = re.compile(r'^\* (Problem .*)')

    # Matches the Task subheading (e.g., "** Task")
    task_pattern = re.compile(r'^\*\* Task')

    # Matches other subheadings to know when a task ends (e.g., "** Solution", "** Notes")
    subheading_pattern = re.compile(r'^\*\* ')

    # Matches org-mode quote blocks
    begin_quote_pattern = re.compile(r'^\s*#\+begin_quote\s*', re.IGNORECASE)
    end_quote_pattern = re.compile(r'^\s*#\+end_quote\s*', re.IGNORECASE)

    # Matches citation markers like \cite{...}
    citation_pattern = re.compile(r'\\cite\{.*?\}')

    # Metadata extraction
    title = "Unknown Title"
    for line in lines:
        if line.lower().startswith("#+title:"):
            title = line.split(":", 1)[1].strip()
            break
    if title == "Unknown Title":
        # Fallback to filename if no title found
        title = Path(file_path).stem

    output_lines = []
    output_lines.append(f"* {title}")

    current_problem_header = None
    in_task_section = False
    task_content = []

    for line in lines:
        # 1. Detect Problem Heading (Level 1)
        match_prob = problem_pattern.match(line)
        if match_prob:
            # If we were processing a previous task, save it before starting new problem
            if current_problem_header and task_content:
                output_lines.append(current_problem_header)
                output_lines.extend(clean_content(task_content, citation_pattern, begin_quote_pattern, end_quote_pattern))
                task_content = []

            # Store new header (e.g., "** Problem 1") - Note: converted to Level 2 per rules
            current_problem_header = "** " + match_prob.group(1).strip()
            in_task_section = False
            continue

        # 2. Detect Task Subheading (Level 2)
        if task_pattern.match(line):
            in_task_section = True
            continue

        # 3. Detect End of Task (any other Level 2 subheading or higher)
        if subheading_pattern.match(line) and not task_pattern.match(line):
            in_task_section = False
            continue

        # 4. Capture Content
        if in_task_section:
            task_content.append(line)

    # Append the final problem if it exists
    if current_problem_header and task_content:
        output_lines.append(current_problem_header)
        output_lines.extend(clean_content(task_content, citation_pattern, begin_quote_pattern, end_quote_pattern))

    return output_lines

def clean_content(content_lines, citation_pat, b_quote_pat, e_quote_pat):
    """
    Cleans the captured task content:
    - Removes #+begin_quote / #+end_quote lines
    - Removes citation tags
    - Preserves LaTeX ($ and $$)
    - Trims extra empty lines at start/end
    """
    cleaned = []
    for line in content_lines:
        # Skip quote block markers
        if b_quote_pat.match(line) or e_quote_pat.match(line):
            continue

        # Remove citations
        line = citation_pat.sub('', line)

        cleaned.append(line)

    # Remove leading/trailing empty lines from the extracted block
    while cleaned and not cleaned[0].strip():
        cleaned.pop(0)
    while cleaned and not cleaned[-1].strip():
        cleaned.pop()

    return cleaned

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Concatenate the Task sections of every ps_NN.org under a "
                    "problem-set directory into one org file.")
    ap.add_argument("--ps-dir", type=Path, default=Path.cwd(),
                    help="directory containing ps_NN/ (default: cwd)")
    ap.add_argument("--out", type=Path, required=True,
                    help="output file to write")
    args = ap.parse_args()

    if not args.ps_dir.is_dir():
        print(f"not a directory: {args.ps_dir}", file=sys.stderr)
        return 1

    org_files = sorted(args.ps_dir.rglob("ps_*.org"))
    if not org_files:
        print(f"no ps_*.org under {args.ps_dir}", file=sys.stderr)
        return 1

    lines = []
    failed = 0
    for path in org_files:
        try:
            lines.extend(extract_problems(str(path)))
        except Exception as exc:
            print(f"error processing {path}: {exc}", file=sys.stderr)
            failed += 1

    text = "".join(l if l.endswith("\n") else l + "\n" for l in lines)
    args.out.write_text(text, encoding="utf-8")
    print(f"wrote {len(org_files) - failed} file(s) -> {args.out}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
