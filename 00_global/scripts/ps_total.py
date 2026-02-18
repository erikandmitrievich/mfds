#!/usr/bin/env python3

import re
import sys

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

    # Matches citation markers like or
    citation_pattern = re.compile(r'\\')

    # Metadata extraction
    title = "Unknown Title"
    for line in lines:
        if line.lower().startswith("#+title:"):
            title = line.split(":", 1)[1].strip()
            break
    if title == "Unknown Title":
        # Fallback to filename if no title found
        title = file_path.split('/')[-1].replace('.org', '')

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

def main():
    if len(sys.argv) < 2:
        print("Usage: python extract_ps.py <file1.org> <file2.org> ...")
        sys.exit(1)

    all_output = []

    # Process each file provided as an argument
    for file_path in sys.argv[1:]:
        try:
            file_output = extract_problems(file_path)
            all_output.extend(file_output)
        except Exception as e:
            print(f"Error processing {file_path}: {e}", file=sys.stderr)

    # Print Result inside a code block
    print("#+begin_src org")
    for line in all_output:
        print(line, end='')
        # Ensure newlines are preserved correctly (print adds one by default, content usually has one)
        if not line.endswith('\n'):
            print()
    print("\n#+end_src")

if __name__ == "__main__":
    main()
